"""A durable PostgreSQL job worker. No external scheduler or in-memory queue."""

from datetime import timedelta
import logging
import time

from sqlalchemy import select

from .database import SessionLocal
from .knowledge import crawl_source
from .models import Job, Source, utcnow


logger = logging.getLogger(__name__)


def fail_stale_jobs(db):
    stale = db.scalars(select(Job).where(Job.status == "running", Job.updated_at < utcnow() - timedelta(minutes=30))
                       .with_for_update(skip_locked=True)).all()
    for job in stale:
        job.status, job.error, job.updated_at = "failed", "Worker 中斷或心跳超過 30 分鐘，請檢查後重新同步", utcnow()
        source = db.get(Source, job.source_id)
        if source:
            source.status = "failed"
    db.commit()


def run_once():
    with SessionLocal() as db:
        fail_stale_jobs(db)
        job = db.scalar(select(Job).where(Job.status == "queued").order_by(Job.created_at, Job.id)
                        .with_for_update(skip_locked=True).limit(1))
        if not job:
            db.rollback()
            return False
        job.status, job.updated_at = "running", utcnow()
        job_id = job.id
        db.commit()  # Claim is durable before the first network request.
        source = db.get(Source, job.source_id)
        try:
            if not source:
                raise ValueError("擷取來源不存在")
            crawl_source(db, source, job)
        except Exception:
            db.rollback()
            # Do not log response bodies/URLs/credentials into global logs.
            logger.error("知識擷取任務 %s 失敗；請檢查任務狀態", job_id)
            job = db.get(Job, job_id)
            job.status, job.error, job.updated_at = "failed", "擷取執行失敗，已保留先前草稿；請檢查來源或資料庫狀態", utcnow()
            source = db.get(Source, job.source_id)
            if source:
                source.status = "failed"
            db.commit()
        return True


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            if not run_once():
                time.sleep(2)
        except Exception:
            logger.error("Worker 無法連線資料庫；10 秒後重試")
            time.sleep(10)


if __name__ == "__main__":
    main()
