import { defineConfig } from 'cypress'

export default defineConfig({
  e2e: {
    baseUrl: 'http://localhost:8001', // Django serving console/dist (make console, make dev)
    supportFile: 'cypress/support/e2e.ts',
    specPattern: 'cypress/e2e/**/*.cy.ts',
    video: false,
    setupNodeEvents(on) {
      on('task', {
        log(message: string) {
          console.log(message)
          return null
        },
      })
    },
  },
})
