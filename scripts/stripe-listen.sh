#!/usr/bin/env sh
# Forward Stripe test-mode events to the local webhook and, with `trigger`, fire one.
#
#   scripts/stripe-listen.sh            # prints the whsec_... to put in STRIPE_WEBHOOK_SECRET
#   scripts/stripe-listen.sh trigger    # stripe trigger payment_intent.succeeded
#
# Needs `stripe login` once. The forwarded PaymentIntent from `trigger` is not one
# Tally created, so the handler acknowledges it and books nothing; a real round trip
# is `uv run pytest -m live` with STRIPE_TEST_SECRET_KEY set.
set -eu
PORT="${PORT:-8001}"
case "${1:-listen}" in
  listen)  exec stripe listen --forward-to "localhost:${PORT}/webhooks/stripe" ;;
  trigger) exec stripe trigger payment_intent.succeeded ;;
  *) echo "usage: $0 [listen|trigger]" >&2; exit 2 ;;
esac
