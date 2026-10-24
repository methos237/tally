// Runs against Django on 8001 serving the production build, seed_demo applied.

describe('sign in', () => {
  it('redirects a visitor to the login page and signs the operator in', () => {
    cy.visit('/journal')
    cy.location('pathname').should('eq', '/login')
    cy.checkPage()
    cy.get('input[autocomplete=username]').type('ops')
    cy.get('input[type=password]').type('ops-demo')
    cy.contains('button', 'Sign in').click()
    cy.location('pathname').should('eq', '/journal')
    cy.contains('ops · Acme Corp')
  })

  it('rejects a wrong password with the problem detail', () => {
    cy.visit('/login')
    cy.get('input[autocomplete=username]').type('ops')
    cy.get('input[type=password]').type('nope')
    cy.contains('button', 'Sign in').click()
    cy.get('[role=alert]').should('contain', 'Wrong username or password')
  })
})

describe('pages', () => {
  beforeEach(() => cy.login())

  for (const [path, heading] of [
    ['/', 'Dashboard'],
    ['/journal', 'Journal'],
    ['/accounts', 'Accounts'],
    ['/billing', 'Subscriptions'],
    ['/webhooks', 'Webhook endpoints'],
    ['/reconciliation', 'Reconciliation workbench'],
    ['/reports', 'Partner daily reports'],
  ]) {
    it(`${path} renders and passes WCAG 2.2 AA`, () => {
      cy.visit(path)
      cy.contains('h2', heading)
      cy.get('table, dl, nav[aria-label=Statements], [data-empty]').should('exist') // data or empty state
      cy.checkPage()
    })
  }

  it('browses the journal with a filter and opens an entry', () => {
    cy.visit('/journal')
    cy.get('tbody tr').should('have.length', 50)
    cy.contains('label', 'Source type').find('input').type('invoice')
    cy.contains('button', 'Filter').click()
    cy.get('tbody tr').each(($row) => expect($row.text()).to.contain('invoice'))
    cy.get('tbody tr').first().click()
    cy.get('aside[aria-label="Entry detail"]').within(() => {
      cy.contains('Journal lines')
      cy.get('tbody tr').should('have.length.at.least', 2)
    })
    cy.checkPage()
  })

  it('resolves a reconciliation exception and the journal shows the adjusting entry', () => {
    cy.visit('/reconciliation')
    cy.get('nav[aria-label=Statements] button').first().click()
    cy.get('article:has(button)')
      .its('length')
      .then((open) => {
        cy.get('article:has(button)').first().as('card')
        cy.get('@card').find('h3').invoke('text').as('title')
        cy.get('@card').contains('button', 'Resolve').click()
        cy.get('dialog').within(() => {
          cy.checkPage()
          cy.get('input[value=adjust]').check()
          cy.get('input[placeholder]').type('6100')
          cy.contains('button', 'Resolve').click()
        })
        cy.get('dialog').should('not.exist')
        cy.get('article:has(button)').should('have.length', open - 1)
      })
    cy.visit('/journal')
    cy.contains('label', 'Source type').find('input').type('adjustment')
    cy.contains('button', 'Filter').click()
    cy.get('tbody tr').first().click()
    cy.get('aside[aria-label="Entry detail"]').contains('6100')
  })

  it('redelivers a dead letter', () => {
    cy.visit('/webhooks')
    cy.get('tbody tr').first().click()
    cy.get('section tbody tr')
      .its('length')
      .then((dead) => {
        expect(dead).to.be.greaterThan(0)
        cy.get('section tbody tr').first().contains('button', 'Redeliver').click()
        cy.get('section tbody tr, section p').should(($el) => {
          expect($el.filter('tr')).to.have.length(dead - 1)
        })
      })
    cy.checkPage()
  })
})
