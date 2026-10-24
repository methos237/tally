import 'cypress-axe'

declare global {
  namespace Cypress {
    interface Chainable {
      /** Sign in as the seeded operator through the session API; cached across tests. */
      login(): Chainable<void>
      /** axe at WCAG 2.2 AA on the current page. */
      checkPage(): Chainable<void>
    }
  }
}

Cypress.Commands.add('login', () => {
  cy.session('ops', () => {
    cy.request({ url: '/console/session', failOnStatusCode: false }).then(() => {
      cy.getCookie('csrftoken').then((cookie) => {
        cy.request({
          method: 'POST',
          url: '/console/login',
          body: { username: 'ops', password: 'ops-demo' },
          headers: { 'X-CSRFToken': cookie!.value },
        })
      })
    })
  })
})

Cypress.Commands.add('checkPage', () => {
  cy.injectAxe()
  cy.checkA11y(
    undefined,
    { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] } },
    (violations) => {
      for (const v of violations) {
        cy.task(
          'log',
          `axe ${v.id} (${v.impact}): ${v.help} -> ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`,
        )
      }
    },
  )
})
