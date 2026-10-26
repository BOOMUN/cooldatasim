import { createApp } from 'vue'
import App from './App.vue'
import { nativeValidationMessage } from './localization'
import './style.css'

function formControl(target: EventTarget | null) {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement ? target : null
}
document.addEventListener('invalid', event => {
  const control = formControl(event.target)
  if (control) { control.setCustomValidity(''); control.setCustomValidity(nativeValidationMessage(control.validity)) }
}, true)
for (const eventName of ['input', 'change']) {
  document.addEventListener(eventName, event => formControl(event.target)?.setCustomValidity(''), true)
}

createApp(App).mount('#app')
