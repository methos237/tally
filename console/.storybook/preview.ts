import type { Preview } from '@storybook/vue3-vite'

import '../src/assets/main.css'

const preview: Preview = {
  parameters: { a11y: { test: 'error' } }, // WCAG violations fail the story
}

export default preview
