import { config } from '@vue/test-utils'

// jsdom does not implement these; several components use them.
if (typeof window !== 'undefined') {
  window.scrollTo = window.scrollTo ?? (() => undefined)
}

config.global.stubs = {
  RouterLink: {
    props: ['to'],
    template: '<a :href="typeof to === \'string\' ? to : \'#\'"><slot /></a>',
  },
  RouterView: true,
}

import { beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  vi.restoreAllMocks()
})
