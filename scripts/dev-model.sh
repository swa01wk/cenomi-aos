#!/usr/bin/env bash
# Switch the Compose worker between the scripted model and the real one, writing .env.
#
#   scripts/dev-model.sh real   AOS_RUNTIME=langgraph; asks for the OpenAI key, model and prices when missing
#   scripts/dev-model.sh fake   AOS_RUNTIME=fake (the scripted model; CI and the e2e stops 4–5 use it)
#
# The key is read without echo and only written to .env (git-ignored). Prices are USD per million tokens and
# drive ModelInvoked cost and the Seat's daily limit: check them on OpenAI's pricing page.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=.env
[ -f "$ENV_FILE" ] || cp .env.example "$ENV_FILE"
# shellcheck source=env-lib.sh
source scripts/env-lib.sh

DEFAULT_MODEL=gpt-5.4-mini
# gpt-5.4-mini list prices as of Oct 2026 (USD per million tokens). Confirm on OpenAI's pricing page.
DEFAULT_PRICE_IN=0.75
DEFAULT_PRICE_OUT=4.50

ask() { # ask "question" default -> prints the answer, or the default on Enter (prompt goes to stderr)
  local answer
  read -r -p "$1 [$2]: " answer </dev/tty
  printf '%s' "${answer:-$2}"
}

case "${1:-}" in
  fake)
    set_value AOS_RUNTIME fake
    echo "AOS_RUNTIME=fake (scripted model). Run 'make up' to apply."
    ;;
  real)
    interactive=0
    # A terminal we can actually open (not just a /dev/tty node), e.g. not in CI.
    if (exec </dev/tty) 2>/dev/null; then interactive=1; fi

    key=$(env_value OPENAI_API_KEY)
    if [ -z "$key" ]; then
      [ "$interactive" = 1 ] || { echo "OPENAI_API_KEY is not set in .env" >&2; exit 1; }
      read -r -s -p "OpenAI API key (input hidden): " key </dev/tty
      echo
      [ -n "$key" ] || { echo "No key given" >&2; exit 1; }
      set_value OPENAI_API_KEY "$key"
    else
      echo "OPENAI_API_KEY: already set in .env"
    fi

    model=$(env_value OPENAI_MODEL)
    price_in=$(env_value AOS_MODEL_PRICE_IN_PER_MTOK)
    price_out=$(env_value AOS_MODEL_PRICE_OUT_PER_MTOK)
    if [ "$interactive" = 1 ]; then
      model=$(ask "Model" "${model:-$DEFAULT_MODEL}")
      echo "Prices in USD per million tokens; Enter keeps the value shown. $DEFAULT_MODEL listed at"
      echo "in $DEFAULT_PRICE_IN / out $DEFAULT_PRICE_OUT as of Oct 2026 (check OpenAI's pricing page)."
      price_in=$(ask "  input" "${price_in:-$DEFAULT_PRICE_IN}")
      price_out=$(ask "  output" "${price_out:-$DEFAULT_PRICE_OUT}")
    else
      model=${model:-$DEFAULT_MODEL}
      [ -n "$price_in" ] && [ -n "$price_out" ] || { echo "Set both AOS_MODEL_PRICE_* in .env" >&2; exit 1; }
    fi
    set_value OPENAI_MODEL "$model"
    set_value AOS_MODEL_PRICE_IN_PER_MTOK "$price_in"
    set_value AOS_MODEL_PRICE_OUT_PER_MTOK "$price_out"
    [ -n "$(env_value AOS_MODEL_PROVIDER)" ] || set_value AOS_MODEL_PROVIDER openai
    set_value AOS_RUNTIME langgraph
    echo "AOS_RUNTIME=langgraph, model $model, prices in $price_in / out $price_out per million tokens."
    ;;
  *)
    echo "usage: $0 real|fake" >&2
    exit 2
    ;;
esac
