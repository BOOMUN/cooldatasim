import json
from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai, knowledge, worker
from app.config import Settings, settings
from app.database import make_engine
from app.models import Base, Chunk, Document, Job, Product, Source, utcnow


@pytest.fixture
def db(monkeypatch):
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "embedding_base_url", "")
    monkeypatch.setattr(settings, "reranker_base_url", "")
    monkeypatch.setattr(settings, "qwen_base_url", "")
    for name in ("chat_provider", "chat_base_url", "chat_model", "chat_api_key", "chat_reasoning_effort", "chat_session_namespace"):
        monkeypatch.setattr(settings, name, "")
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(knowledge.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])


def test_url_validation_rejects_credentials_nonallowed_host_and_port(public_dns):
    for url in ("file:///etc/passwd", "https://example.com/", "https://name:password@www.cooldatasim.com/", "https://www.cooldatasim.com:444/"):
        with pytest.raises(knowledge.CrawlError):
            knowledge.validate_source_url(url)
    assert knowledge.validate_source_url("https://www.cooldatasim.com/日本#fragment").endswith("/%E6%97%A5%E6%9C%AC")


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1", "0.0.0.0", "224.0.0.1"])
def test_dns_private_and_metadata_addresses_are_rejected(monkeypatch, address):
    monkeypatch.setattr(knowledge.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (address, 443))])
    monkeypatch.setattr(knowledge, "_public_dns", Mock(side_effect=knowledge.CrawlError("非公開 DNS 結果")))
    with pytest.raises(knowledge.CrawlError, match="非公開"):
        knowledge.validate_source_url("https://www.cooldatasim.com/")


def test_doh_uses_fixed_provider_and_public_answer_only(monkeypatch):
    response = Mock(status_code=200, content=b"dns answer")
    response.json.return_value = {"Status": 0, "Question": [{"name": "www.cooldatasim.com.", "type": 1}],
                                  "Answer": [{"type": 1, "data": "93.184.216.34"}]}
    client = Mock()
    client.get.return_value = response
    constructor = Mock(side_effect=lambda **kwargs: nullcontext(client))
    monkeypatch.setattr(knowledge.httpx, "Client", constructor)
    assert knowledge._public_dns("www.cooldatasim.com") == {"93.184.216.34"}
    assert client.get.call_args.args[0] == "https://dns.google/resolve"
    assert constructor.call_args.kwargs == {"timeout": 10, "follow_redirects": False, "trust_env": False}
    response.json.return_value["Answer"] = [{"type": 1, "data": "169.254.169.254"}]
    with pytest.raises(knowledge.CrawlError, match="安全結果"):
        knowledge._public_dns("www.cooldatasim.com")
    assert all(call.args[0] in knowledge.DOH_ENDPOINTS for call in client.get.call_args_list)


def test_doh_different_question_cannot_override_requested_hostname(monkeypatch):
    response = Mock(status_code=200, content=b"dns answer")
    response.json.return_value = {"Status": 0, "Question": [{"name": "attacker.example.", "type": 1}],
                                  "Answer": [{"type": 1, "data": "93.184.216.34"}]}
    client = Mock()
    client.get.return_value = response
    monkeypatch.setattr(knowledge.httpx, "Client", lambda **kwargs: nullcontext(client))
    with pytest.raises(knowledge.CrawlError):
        knowledge._public_dns("www.cooldatasim.com")


def test_fake_ip_is_never_used_as_page_destination(monkeypatch):
    monkeypatch.setattr(knowledge.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("198.18.0.96", 443))])
    monkeypatch.setattr(knowledge, "_public_dns", lambda hostname: {"93.184.216.34"})
    assert knowledge._validated_target("https://www.cooldatasim.com/")[1] == "93.184.216.34"


def test_request_pins_public_ip_and_preserves_tls_hostname(monkeypatch, public_dns):
    response = Mock(status_code=200, headers={"content-type": "text/html"})
    response.iter_bytes.return_value = [b"<html>safe</html>"]
    client = Mock()
    client.stream.return_value = nullcontext(response)
    constructor = Mock(return_value=nullcontext(client))
    monkeypatch.setattr(knowledge.httpx, "Client", constructor)
    assert knowledge._fetch_once("https://www.cooldatasim.com/page")[0] == 200
    assert constructor.call_args.kwargs["trust_env"] is False
    assert client.stream.call_args.args[1] == "https://93.184.216.34/page"
    assert client.stream.call_args.kwargs["headers"]["Host"] == "www.cooldatasim.com"
    assert client.stream.call_args.kwargs["extensions"]["sni_hostname"] == "www.cooldatasim.com"


def test_cross_site_redirect_is_rejected(monkeypatch):
    mocked = Mock(return_value=(302, {"location": "http://169.254.169.254/latest/meta-data"}, b"", "https://www.cooldatasim.com/"))
    monkeypatch.setattr(knowledge, "_fetch_once", mocked)
    with pytest.raises(knowledge.CrawlError, match="其他網站"):
        knowledge._fetch("https://www.cooldatasim.com/", "cooldatasim.com")
    assert mocked.call_count == 1


def test_robots_denial_and_unavailable_fail_closed(monkeypatch):
    monkeypatch.setattr(knowledge, "_fetch", lambda *a: (200, {}, b"User-agent: *\nDisallow: /secret\n", ""))
    with pytest.raises(knowledge.CrawlError, match="robots"):
        knowledge._Robots("cooldatasim.com").check("https://www.cooldatasim.com/secret")
    monkeypatch.setattr(knowledge, "_fetch", lambda *a: (503, {}, b"", ""))
    with pytest.raises(knowledge.CrawlError, match="許可"):
        knowledge._Robots("cooldatasim.com").check("https://www.cooldatasim.com/")


def test_robots_wildcards_specific_user_agent_and_allow_priority():
    lines = "User-agent: MJ12bot\nDisallow: /\n\nUser-agent: *\nDisallow: /*?*draft=*\nDisallow: /private\nAllow: /private/public\n".splitlines()
    assert knowledge._robots_allowed(lines, "https://www.cooldatasim.com/products/japan")
    assert not knowledge._robots_allowed(lines, "https://www.cooldatasim.com/products/japan?x=1&draft=true")
    assert not knowledge._robots_allowed(lines, "https://www.cooldatasim.com/private/data")
    assert knowledge._robots_allowed(lines, "https://www.cooldatasim.com/private/public/page")


def test_schema_product_uses_actual_offer_and_unknown_range_is_null():
    page = '<html><title>Test</title><main><h1>Japan 7 days 10GB eSIM</h1><p>Activation guide</p></main><script type="application/ld+json">' + json.dumps({
        "@graph": [{"@type": "Product", "name": "Japan 7 days 10GB eSIM", "offers": {"@type": "Offer", "price": 93, "priceCurrency": "HKD"}}]
    }) + "</script></html>"
    _, content, products, _ = knowledge.parse_page(page, "https://www.cooldatasim.com/products/test")
    assert products[0]["price"] == 93
    assert products[0]["days"] == 7
    assert products[0]["country"] == "日本"
    assert products[0]["card_type"] == "eSIM"
    assert "@graph" not in content
    page = page.replace('"Offer", "price": 93', '"AggregateOffer", "lowPrice": 93')
    assert knowledge.parse_page(page, "https://www.cooldatasim.com/products/test")[2][0]["price"] is None


def test_destination_labels_are_traditional_without_losing_simplified_input():
    assert knowledge.extract_destinations("韩国 台湾 中国 澳门 马来西亚") == {"韓國", "台灣", "中國", "澳門", "馬來西亞"}
    assert knowledge.extract_destinations("韓國 台灣 中國 澳門 馬來西亞") == {"韓國", "台灣", "中國", "澳門", "馬來西亞"}
    assert knowledge.extract_destinations("中港澳") == {"中國", "香港", "澳門"}
    assert knowledge.extract_card_type("电子SIM") == "eSIM"
    assert knowledge.extract_card_type("实体卡") == "SIM"


def test_ingestion_does_not_convert_the_original_website_text():
    original = "这是网站原始简体内容：韩国七天套餐，实际服务以页面说明为准。"
    _, content, _, _ = knowledge.parse_page(f"<html><body><main><h1>原始资料</h1><p>{original}</p></main></body></html>", "https://www.cooldatasim.com/pages/test")
    assert original in content


def test_simplified_country_query_retrieves_traditional_product_and_knowledge(db):
    product = Product(name="韓國上網卡", country="韓國", days=7, card_type="SIM", price=93, currency="HKD", url="https://www.cooldatasim.com/products/korea", status="published")
    document = Document(title="韓國使用說明", content="韓國上網卡使用方式請參閱這份已審核說明。", url="https://www.cooldatasim.com/pages/korea")
    db.add_all([product, document])
    db.flush()
    knowledge.publish_document(db, document)
    evidence = ai.retrieve(db, "韩国")[0]
    assert {item["id"] for item in evidence} == {f"product-{product.id}", f"doc-{document.id}"}


def test_shopline_product_discards_shell_but_preserves_description_and_delivery():
    page = """<html><head><title>Japan package</title></head><body>
    <div id="shopline-section-header">首頁 所有商品</div>
    <div id="MenuPanel">覆蓋國家 韓國 泰國 日本</div>
    <div id="LanguagePanel">English 繁體中文</div><div id="CurrencyPanel">HKD USD</div>
    <div id="cart-panel">會員登入 {{ cart.checkout }} 購物車是空的</div>
    <div id="Content"><div class="ProductDetail-loading-data">Japan package</div>
      <div class="ProductDetail-product-info js-product-info">
        <h1 class="Product-title">Japan package</h1>
        <p class="Product-summary">先選擇使用天數。需要延長方案請聯絡客服。</p>
        <div class="same-price">{{ product.price }}</div>
        <div class="txt-notify">售完</div><div class="out-of-stock">products.quantity_limit99999</div>
        <div class="ProductDetail-additionalInfo">
          <div class="ProductDetail-description"><h2>商品描述</h2><p>取卡後88天內啟用；套餐仍為七日。</p><p>售後問題請保留訂單編號。</p></div>
          <div class="ProductDetail-shipping-payment"><h2>送貨及付款方式</h2><p>機場櫃檯24小時取卡。</p><p>可使用信用卡付款。</p></div>
        </div>
      </div><div class="related-products">您可能喜歡 韓國商品</div>
    </div><div id="shopline-section-footer">聯絡我們 隱私政策 Copyright</div>
    </body></html>"""
    _, content, _, _ = knowledge.parse_page(page, "https://www.cooldatasim.com/products/test")
    for pollution in ("首頁", "所有商品", "覆蓋國家", "會員登入", "English", "HKD", "購物車", "售完", "quantity_limit", "Copyright", "您可能喜歡"):
        assert pollution not in content
    for required in ("先選擇使用天數", "88天內啟用", "七日", "售後問題", "24小時取卡", "信用卡付款"):
        assert required in content
    assert content.count("Japan package") == 1


def test_shopline_custom_page_extracts_faq_without_drawer_or_footer():
    page = """<html><body><div id="MenuPanel">所有商品 韓國 日本</div>
    <div id="Content"><div class="CustomPage-text-page"><h1>常見問題</h1>
      <div class="CustomPage-content"><h2>常見問題</h2><p>Q1. 如何取卡？</p><p>請攜帶訂單確認資訊到指定櫃檯。</p>
      <p>Q2. 啟用失敗怎麼辦？</p><p>請向客服提供裝置型號。</p></div></div></div>
    <div id="shopline-section-footer">Copyright 隱私政策</div></body></html>"""
    _, content, _, _ = knowledge.parse_page(page, "https://www.cooldatasim.com/pages/faq")
    assert "所有商品" not in content and "Copyright" not in content
    assert "如何取卡" in content and "啟用失敗" in content
    assert content.count("常見問題") == 1


def test_inline_numbers_keep_sentence_context_and_repeated_values():
    page = '<html><body><main><!-- HIDDEN_TEMPLATE_COMMENT --><h1>取卡規則</h1><p>取卡須在<strong>21</strong>天內完成。</p><p>另一項期限也是<strong>21</strong>天。</p></main></body></html>'
    _, content, _, _ = knowledge.parse_page(page, "https://www.cooldatasim.com/pages/test")
    assert "取卡須在21天內完成。" in content
    assert "另一項期限也是21天。" in content
    assert "HIDDEN_TEMPLATE_COMMENT" not in content


def test_published_snapshot_survives_draft_edit_and_withdraw_removes_evidence(db):
    doc = Document(title="Japan guide", content="Japan activation known published instructions", url="https://www.cooldatasim.com/pages/test")
    draft = Document(title="Japan secret", content="Japan UNPUBLISHED DRAFT", url="")
    db.add_all([doc, draft])
    db.flush()
    knowledge.publish_document(db, doc)
    doc.content = "Japan unapproved revision"
    doc.title = "unapproved title"
    doc.status = "draft"
    db.flush()
    evidence, mode, trace = ai.retrieve(db, "Japan activation")
    assert mode == "keyword"
    assert evidence and "known published" in evidence[0]["text"]
    assert all("unapproved" not in entry["text"] and "UNPUBLISHED" not in entry["text"] for entry in evidence)
    assert evidence[0]["title"] == "Japan guide"
    assert doc.vector_status == "text_only"
    knowledge.withdraw_document(db, doc)
    assert ai.retrieve(db, "Japan activation")[0] == []
    assert list(db.scalars(select(Chunk))) == []


def test_failed_embedding_does_not_destroy_old_publication(db, monkeypatch):
    doc = Document(title="Japan", content="Japan previously published guide", url="")
    db.add(doc)
    db.flush()
    knowledge.publish_document(db, doc)
    db.commit()
    doc.content = "New pending version"
    monkeypatch.setattr(settings, "embedding_base_url", "http://model.invalid/v1")
    monkeypatch.setattr(ai, "_request", Mock(side_effect=ai.ModelUnavailable("HTTP 503")))
    with pytest.raises(ai.ModelUnavailable):
        knowledge.publish_document(db, doc)
    assert doc.published_content == "Japan previously published guide"
    assert db.scalar(select(Chunk)).body == "Japan previously published guide"


def test_model_missing_is_not_a_fake_answer(db):
    with pytest.raises(ai.ModelUnavailable, match="對話模型尚未設定"):
        ai.generate_answer(db, "日本七天多少钱")
    assert ai.probe_models()["qwen"]["status"] == "not_configured"


@pytest.mark.parametrize("vector", [[1.0] * 384, [0.0] * 1024, [float("nan")] * 1024, [True] * 1024, [1e308] * 1024])
def test_invalid_vector_rejected(vector):
    with pytest.raises(ai.ModelUnavailable):
        ai.validate_vector(vector)


def test_embedding_requires_exact_indexes_and_uses_separate_key(monkeypatch):
    monkeypatch.setattr(settings, "embedding_base_url", "http://embedding.invalid/v1")
    monkeypatch.setattr(settings, "embedding_api_key", "embedding-test-only")
    request = Mock(return_value={"data": [{"index": 0, "embedding": [1.0] * 1024}]})
    monkeypatch.setattr(ai, "_request", request)
    assert len(ai.embed_texts(["Japan"])[0]) == 1024
    assert request.call_args.args[:3] == ("http://embedding.invalid/v1", "/embeddings", "embedding-test-only")
    request.return_value = {"data": [{"index": 4, "embedding": [1.0] * 1024}]}
    with pytest.raises(ai.ModelUnavailable, match="數量"):
        ai.embed_texts(["Japan"])


def test_embedding_distinguishes_document_and_query_inputs(monkeypatch):
    monkeypatch.setattr(settings, "embedding_base_url", "http://embedding.invalid/v1")
    request = Mock(return_value={"model": settings.embedding_model,
                                 "data": [{"index": 0, "embedding": [1.0] * 1024}]})
    monkeypatch.setattr(ai, "_request", request)
    ai.embed_texts(["已發布的知識文字"])
    assert request.call_args.args[3]["input_type"] == "document"
    ai.embed_texts(["客戶的問題"], query=True)
    assert request.call_args.args[3]["input_type"] == "query"


def test_embedding_rejects_another_model_and_boolean_indexes(monkeypatch):
    monkeypatch.setattr(settings, "embedding_base_url", "http://embedding.invalid/v1")
    request = Mock(return_value={"model": "another-model", "data": [{"index": 0, "embedding": [1.0] * 1024}]})
    monkeypatch.setattr(ai, "_request", request)
    with pytest.raises(ai.ModelUnavailable):
        ai.embed_texts(["知識文字"])
    request.return_value = {"model": settings.embedding_model,
                            "data": [{"index": False, "embedding": [1.0] * 1024}]}
    with pytest.raises(ai.ModelUnavailable):
        ai.embed_texts(["知識文字"])


def test_query_vectors_exclude_mixed_models_and_handle_finite_extremes(db, monkeypatch):
    eligible = Document(title="Vector-only evidence", content="Marker alpha", published_content="Marker alpha", status="published")
    foreign = Document(title="Different model", content="Marker beta", published_content="Marker beta", status="published")
    db.add_all([eligible, foreign])
    db.flush()
    db.add_all([
        Chunk(document_id=eligible.id, body="Marker alpha", embedding=[1e-300] + [0.0] * 1023, model=settings.embedding_model),
        Chunk(document_id=foreign.id, body="Marker beta", embedding=[1.0] * 384, model="old-384-model"),
    ])
    db.flush()
    monkeypatch.setattr(settings, "embedding_base_url", "http://embedding.invalid/v1")
    request = Mock(return_value={"model": settings.embedding_model,
                                 "data": [{"index": 0, "embedding": [1e300] + [0.0] * 1023}]})
    monkeypatch.setattr(ai, "_request", request)
    evidence, mode, _ = ai.retrieve(db, "完全不同的語意問題")
    assert request.call_args.args[3]["input_type"] == "query"
    assert mode == "hybrid"
    assert [item["id"] for item in evidence] == [f"doc-{eligible.id}"]


def test_langgraph_calls_qwen_and_validates_citations(db, monkeypatch):
    doc = Document(title="Japan guide", content="Japan activation uses scanned QR code", url="https://www.cooldatasim.com/pages/test")
    db.add(doc)
    db.flush()
    knowledge.publish_document(db, doc)
    monkeypatch.setattr(settings, "qwen_base_url", "http://qwen.invalid/v1")
    request = Mock(return_value={"choices": [{"message": {"content": json.dumps({"answer": "Scan the QR code.", "source_ids": [f"doc-{doc.id}"], "needs_human": False})}}]})
    monkeypatch.setattr(ai, "_request", request)
    answer = ai.generate_answer(db, "Japan activation")
    assert answer["status"] == "draft"
    assert answer["citations"][0]["url"] == doc.url
    assert answer["trace"][0] == "LangGraph：檢索"
    assert answer["trace"][-1].startswith("LangGraph：驗證")
    assert request.call_args.args[1] == "/chat/completions"
    assert request.call_args.args[3]["temperature"] == 0.1
    assert "thinking" not in request.call_args.args[3]
    request.return_value["choices"][0]["message"]["content"] = json.dumps({"answer": "Invented", "source_ids": ["doc-9999"], "needs_human": False})
    with pytest.raises(ai.ModelUnavailable, match="來源驗證"):
        ai.generate_answer(db, "Japan activation")


def test_chat_configuration_falls_back_only_when_entire_group_is_empty():
    config = Settings(qwen_base_url="http://qwen.invalid/v1", qwen_model="qwen-test", qwen_api_key="private-qwen-test-key",
                      chat_provider="", chat_base_url="", chat_model="", chat_api_key="", chat_reasoning_effort="")
    assert (config.active_chat_provider, config.active_chat_base_url, config.active_chat_model, config.active_chat_api_key) == (
        "qwen", "http://qwen.invalid/v1", "qwen-test", "private-qwen-test-key")
    assert config.active_chat_reasoning_effort == ""
    config.chat_provider = "opencode"
    assert config.active_chat_base_url == ""
    assert config.active_chat_model == ""
    assert config.active_chat_api_key == ""
    config.chat_base_url = "https://external.invalid/v1"
    config.chat_model = "deepseek-test"
    assert config.active_chat_api_key == ""  # Never reuse Qwen credentials for a new host.
    assert config.active_chat_reasoning_effort == "high"


@pytest.mark.parametrize("provider", ["opencode", "deepseek"])
def test_deepseek_high_uses_final_json_without_exposing_reasoning(db, monkeypatch, provider):
    monkeypatch.setattr(settings, "chat_provider", provider)
    monkeypatch.setattr(settings, "chat_base_url", "https://chat.invalid/v1")
    monkeypatch.setattr(settings, "chat_model", "deepseek-v4.1-flash")
    monkeypatch.setattr(settings, "chat_api_key", "chat-test-only")
    monkeypatch.setattr(settings, "chat_reasoning_effort", "high")
    request = Mock(return_value={"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"answer": "請提供目的地與使用天數。", "source_ids": [], "needs_human": True}),
        "reasoning_content": "PRIVATE_REASONING_MUST_NOT_APPEAR"}}]})
    monkeypatch.setattr(ai, "_request", request)
    answer = ai.generate_answer(db, "請推薦套餐", history=[
        {"role": "system", "content": "UNTRUSTED_SYSTEM_HISTORY"},
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "PRIVATE_IMAGE"}}]},
        {"role": "user", "content": "準備去旅行"},
    ])
    assert request.call_args.args[:3] == ("https://chat.invalid/v1", "/chat/completions", "chat-test-only")
    payload = request.call_args.args[3]
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_tokens"] >= 8192
    assert "temperature" not in payload
    if provider == "opencode":
        assert request.call_args.kwargs["extra_headers"]["User-Agent"] == "CoolDataSim-CustomerCare/0.1"
    else:
        assert request.call_args.kwargs == {}
    assert all(isinstance(message["content"], str) for message in payload["messages"])
    assert "PRIVATE_IMAGE" not in json.dumps(payload)
    assert "UNTRUSTED_SYSTEM_HISTORY" not in json.dumps(payload)
    assert "PRIVATE_REASONING" not in json.dumps(answer)
    assert set(answer) == {"answer", "citations", "status", "trace", "retrieval_mode"}
    assert answer["answer"] == "請提供目的地與使用天數。"
    assert any("deepseek-v4.1-flash" in line for line in answer["trace"])
    monkeypatch.setattr(settings, "chat_reasoning_effort", "medium")
    ai.generate_answer(db, "請推薦套餐")
    assert request.call_args.args[3]["reasoning_effort"] == "medium"


def test_opencode_session_is_stable_private_and_scoped_to_deployment(db, monkeypatch):
    monkeypatch.setattr(settings, "chat_provider", "opencode")
    monkeypatch.setattr(settings, "chat_base_url", "https://chat.invalid/v1")
    monkeypatch.setattr(settings, "chat_model", "deepseek-test")
    monkeypatch.setattr(settings, "chat_session_namespace", "deployment-test-only")
    request = Mock(return_value={"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"answer": "請提供目的地。", "source_ids": [], "needs_human": True})}}]})
    monkeypatch.setattr(ai, "_request", request)

    def session_header(session_id=None):
        ai.generate_answer(db, "請推薦套餐", session_id=session_id)
        headers = request.call_args.kwargs["extra_headers"]
        assert headers["User-Agent"] == "CoolDataSim-CustomerCare/0.1"
        assert "deployment-test-only" not in json.dumps(headers)
        assert "conversation:" not in json.dumps(headers)
        assert len(headers["x-opencode-session"]) == len("ses_cds_") + 32
        return headers["x-opencode-session"]

    first = session_header("conversation:123")
    assert first == session_header("conversation:123")
    assert first != session_header("conversation:456")
    assert first != session_header("preview:123")
    monkeypatch.setattr(settings, "chat_session_namespace", "another-deployment-test-only")
    assert first != session_header("conversation:123")
    assert session_header() != session_header()


def test_embedding_and_reranker_do_not_receive_opencode_session_headers(db, monkeypatch):
    doc = Document(title="Japan guide", content="Japan activation guide", url="https://www.cooldatasim.com/pages/test")
    db.add(doc)
    db.flush()
    knowledge.publish_document(db, doc)
    monkeypatch.setattr(settings, "chat_provider", "opencode")
    monkeypatch.setattr(settings, "embedding_base_url", "http://embedding.invalid/v1")
    request = Mock(return_value={"data": [{"index": 0, "embedding": [1.0] * 1024}]})
    monkeypatch.setattr(ai, "_request", request)
    ai.embed_texts(["Japan"])
    assert request.call_args.kwargs == {}
    monkeypatch.setattr(settings, "embedding_base_url", "")
    monkeypatch.setattr(settings, "reranker_base_url", "http://reranker.invalid/v1")
    request.return_value = {"results": [{"index": 0}]}
    ai.retrieve(db, "Japan activation")
    assert request.call_args.args[1] == "/rerank"
    assert request.call_args.kwargs == {}


def test_truncated_chat_response_is_never_accepted_even_if_json_is_complete(db, monkeypatch):
    monkeypatch.setattr(settings, "qwen_base_url", "http://qwen.invalid/v1")
    request = Mock(return_value={"choices": [{"finish_reason": "length", "message": {
        "content": json.dumps({"answer": "請提供目的地。", "source_ids": [], "needs_human": True})}}]})
    monkeypatch.setattr(ai, "_request", request)
    with pytest.raises(ai.ModelUnavailable, match="截斷"):
        ai.generate_answer(db, "請推薦套餐")


@pytest.mark.parametrize("content", [None, "", "[]"])
def test_reasoning_is_not_used_as_fallback_for_missing_final_content(db, monkeypatch, content):
    monkeypatch.setattr(settings, "qwen_base_url", "http://qwen.invalid/v1")
    request = Mock(return_value={"choices": [{"finish_reason": "stop", "message": {
        "content": content,
        "reasoning_content": json.dumps({"answer": "不可採用的推理", "source_ids": [], "needs_human": True})}}]})
    monkeypatch.setattr(ai, "_request", request)
    with pytest.raises(ai.ModelUnavailable, match="回覆格式") as error:
        ai.generate_answer(db, "請推薦套餐")
    assert "不可採用的推理" not in str(error.value)


def test_chat_probe_reports_provider_and_never_claims_inference(db, monkeypatch):
    monkeypatch.setattr(settings, "chat_provider", "opencode")
    monkeypatch.setattr(settings, "chat_base_url", "https://chat.invalid/v1")
    monkeypatch.setattr(settings, "chat_model", "deepseek-test")
    monkeypatch.setattr(settings, "chat_api_key", "chat-test-only")
    request = Mock(return_value={"data": [{"id": "deepseek-test"}]})
    monkeypatch.setattr(ai, "_request", request)
    result = ai.probe_models()
    assert result["chat"] == {
        "configured": True, "reachable": True, "model": "deepseek-test", "status": "listed",
        "inference_verified": False, "provider": "opencode", "reasoning_effort": "high",
        "detail": "僅模型清單可連線，不代表推理已驗證",
    }
    assert result["qwen"]["alias_of"] == "chat"
    assert "chat-test-only" not in json.dumps(result)
    request.assert_called_once_with("https://chat.invalid/v1", "/models", "chat-test-only")


@pytest.mark.parametrize("path, read_timeout", [("/models", 10), ("/chat/completions", 120), ("/embeddings", 60)])
def test_model_requests_have_separate_probe_and_inference_timeouts(monkeypatch, path, read_timeout):
    client = Mock()
    client.request.return_value.status_code = 200
    client.request.return_value.json.return_value = {"data": []}
    constructor = Mock(return_value=nullcontext(client))
    monkeypatch.setattr(ai.httpx, "Client", constructor)
    ai._request("https://chat.invalid/v1", path, "test-only")
    timeout = constructor.call_args.kwargs["timeout"]
    assert timeout.read == read_timeout
    assert timeout.connect == 10
    assert constructor.call_args.kwargs["follow_redirects"] is False


def test_request_forwards_session_headers_without_changing_authentication(monkeypatch):
    client = Mock()
    client.request.return_value.status_code = 200
    client.request.return_value.json.return_value = {"data": []}
    monkeypatch.setattr(ai.httpx, "Client", Mock(return_value=nullcontext(client)))
    ai._request("https://chat.invalid/v1", "/chat/completions", "test-api-key", {"model": "test"},
                extra_headers={"x-opencode-session": "ses_test", "User-Agent": "CoolDataSim-CustomerCare/0.1"})
    assert client.request.call_args.kwargs["headers"] == {
        "Authorization": "Bearer test-api-key", "x-opencode-session": "ses_test", "User-Agent": "CoolDataSim-CustomerCare/0.1",
    }


def test_unapproved_product_and_unsupported_price_are_blocked(db, monkeypatch):
    db.add(Product(name="Japan", price=5, currency="HKD", url="https://www.cooldatasim.com/products/test", status="draft"))
    db.flush()
    assert ai.retrieve(db, "Japan price")[0] == []
    monkeypatch.setattr(settings, "qwen_base_url", "http://qwen.invalid/v1")
    monkeypatch.setattr(ai, "_request", lambda *a: {"choices": [{"message": {"content": json.dumps({"answer": "HK$99, please confirm", "source_ids": [], "needs_human": True})}}]})
    with pytest.raises(ai.ModelUnavailable, match="價格"):
        ai.generate_answer(db, "Japan price")


def test_price_must_use_currency_of_the_cited_approved_product(db, monkeypatch):
    product = Product(name="Japan", price=93, currency="HKD", url="https://www.cooldatasim.com/products/test", status="published")
    db.add(product)
    db.flush()
    monkeypatch.setattr(settings, "qwen_base_url", "http://qwen.invalid/v1")
    response = {"choices": [{"message": {"content": json.dumps({"answer": "USD 93", "source_ids": [f"product-{product.id}"], "needs_human": False,
                  "price_claims": [{"source_id": f"product-{product.id}", "amount": 93, "currency": "USD"}]})}}]}
    monkeypatch.setattr(ai, "_request", lambda *a: response)
    with pytest.raises(ai.ModelUnavailable, match="幣別"):
        ai.generate_answer(db, "Japan price")
    response["choices"][0]["message"]["content"] = json.dumps({"answer": "HKD 93", "source_ids": [f"product-{product.id}"], "needs_human": False,
            "price_claims": [{"source_id": f"product-{product.id}", "amount": 93, "currency": "HKD"}]})
    assert ai.generate_answer(db, "Japan price")["answer"] == "HKD 93"


def test_product_explicit_country_days_type_are_hard_filters(db):
    records = [
        Product(name="日本7日 SIM Card", country="日本", days=7, card_type="SIM", price=93, currency="HKD", url="https://www.cooldatasim.com/products/jp7", status="published"),
        Product(name="韓國7日 SIM Card", country="韩国", days=7, card_type="SIM", price=93, currency="HKD", url="https://www.cooldatasim.com/products/kr7", status="published"),
        Product(name="日本5日 SIM Card", country="日本", days=5, card_type="SIM", price=50, currency="HKD", url="https://www.cooldatasim.com/products/jp5", status="published"),
        Product(name="日本 eSIM 未知天數", country="日本", days=None, card_type="eSIM", price=93, currency="HKD", url="https://www.cooldatasim.com/products/unknown", status="published"),
    ]
    db.add_all(records)
    db.flush()
    for question in ("日本7日多少钱", "日本七天多少钱", "Japan 7 days price"):
        products = [item for item in ai.retrieve(db, question)[0] if item["kind"] == "product"]
        assert [item["id"] for item in products] == [f"product-{records[0].id}"]
    assert not ai.retrieve(db, "日本7日eSIM多少钱")[0]
    assert not ai.retrieve(db, "多少钱")[0]
    assert not ai.retrieve(db, "7 days price")[0]
    assert not ai.retrieve(db, "日本5日还是7日多少钱")[0]
    assert not ai.retrieve(db, "阿根廷7日多少钱")[0]


def test_price_claim_cannot_borrow_amount_from_another_candidate(db, monkeypatch):
    first = Product(name="Japan SIM Card", country="日本", days=7, card_type="SIM", price=93, currency="HKD", url="https://www.cooldatasim.com/products/first", status="published")
    second = Product(name="Japan eSIM", country="日本", days=7, card_type="eSIM", price=93, currency="HKD", url="https://www.cooldatasim.com/products/second", status="published")
    db.add_all([first, second])
    db.flush()
    monkeypatch.setattr(settings, "qwen_base_url", "http://qwen.invalid/v1")
    body = {"answer": "HKD 93", "source_ids": [f"product-{first.id}"], "needs_human": False,
            "price_claims": [{"source_id": f"product-{second.id}", "amount": 93, "currency": "HKD"}]}
    monkeypatch.setattr(ai, "_request", lambda *a: {"choices": [{"message": {"content": json.dumps(body)}}]})
    with pytest.raises(ai.ModelUnavailable, match="精確綁定"):
        ai.generate_answer(db, "Japan 7 days price")


def test_crawl_only_drafts_and_changed_product_requires_review(db, monkeypatch, public_dns):
    source = Source(name="test", url="https://www.cooldatasim.com/products/test", max_pages=1)
    db.add(source)
    db.flush()
    product = Product(source_id=source.id, name="Japan", price=1, currency="HKD", url=source.url, status="published")
    job = Job(source_id=source.id, status="running")
    db.add_all([product, job])
    db.commit()
    page = '<html><h1>Japan guide</h1><main>Japan activation guide with sufficient public source content.</main><script type="application/ld+json">{"@type":"Product","name":"Japan","offers":{"@type":"Offer","price":2,"priceCurrency":"HKD"}}</script></html>'
    monkeypatch.setattr(knowledge, "_fetch", lambda *a: (200, {"content-type": "text/html"}, page.encode(), source.url))
    knowledge.crawl_source(db, source, job)
    assert job.status == "succeeded"
    assert job.result["published"] is False
    assert product.status == "draft" and product.price == 2
    doc = db.scalar(select(Document))
    assert doc.status == "draft" and doc.published_content is None
    assert doc.category == "product"
    assert ai.retrieve(db, "Japan")[0] == []


def test_bounded_crawl_does_not_claim_full_site_sync(db, monkeypatch, public_dns):
    source = Source(name="bounded", url="https://www.cooldatasim.com/", max_pages=1)
    db.add(source)
    db.flush()
    job = Job(source_id=source.id, status="running")
    db.add(job)
    db.commit()
    page = '<html><h1>Home</h1><main>Public service information with enough useful text to review.<a href="/pages/faq">Frequently asked questions</a></main></html>'
    monkeypatch.setattr(knowledge, "_fetch", lambda *a: (200, {"content-type": "text/html"}, page.encode(), source.url))
    knowledge.crawl_source(db, source, job)
    assert job.status == "succeeded" and source.status == "limited"
    assert job.result["scope"] == "bounded_same_site_html"
    assert job.result["limit_reached"] is True
    assert job.result["remaining_discovered"] == 1
    assert job.result["full_site_verified"] is False
    assert db.scalar(select(Document)).category == "general"


def test_stale_worker_job_is_failed_not_stuck(db):
    source = Source(name="test", url="https://www.cooldatasim.com/", max_pages=1)
    db.add(source)
    db.flush()
    job = Job(source_id=source.id, status="running", updated_at=utcnow() - timedelta(minutes=31))
    db.add(job)
    db.commit()
    worker.fail_stale_jobs(db)
    assert job.status == "failed"
    assert "Worker" in job.error
