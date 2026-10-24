// Lighthouse CI budget for the dashboard, served by Django + whitenoise from the production
// build. The runner signs in first and passes the session cookie (see console.yml).
module.exports = {
  ci: {
    collect: {
      url: ['http://localhost:8001/'],
      numberOfRuns: 3,
      settings: { preset: 'desktop', extraHeaders: process.env.LHCI_EXTRA_HEADERS ?? '{}' },
    },
    assert: {
      assertions: {
        'categories:performance': ['error', { minScore: 0.9 }],
        'categories:accessibility': ['error', { minScore: 0.9 }],
      },
    },
    upload: { target: 'filesystem', outputDir: '.lighthouseci' },
  },
}
