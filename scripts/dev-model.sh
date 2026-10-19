#!/usr/bin/env bash
# Switch the Compose worker between the scripted model and the real one, writing .env.
#
#   scripts/dev-model.sh real   AOS_RUNTIME=langgraph; asks only for the OpenAI key when .env has none
#   scripts/dev-model.sh fake   AOS_RUNTIME=fake (the scripted model; CI and the e2e stops 4–5 use it)
#
# Model and prices default without asking: MODEL (else OPENAI_MODEL in .env, else gpt-5.4-mini), and the list
# prices below for a model we know. Override with MODEL=, PRICE_IN=, PRICE_OUT= (USD per million tokens), e.g.
#   make gate MODEL=gpt-5.4 PRICE_IN=2.50 PRICE_OUT=15
# The key is read without echo and only written to .env (git-ignored). Prices drive ModelInvoked cost and the
# Seat's daily limit.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=.env
[ -f "$ENV_FILE" ] || cp .env.example "$ENV_FILE"
# shellcheck source=env-lib.sh
source scripts/env-lib.sh

DEFAULT_MODEL=gpt-5.4-mini

# List prices, USD per million tokens (input output), as of Oct 2026. Confirm on OpenAI's pricing page.
list_prices() {
  case "$1" in
    gpt-5.4-mini) echo "0.75 4.50" ;;
    *) echo "" ;;
  esac
}

case "${1:-}" in
  fake)
    set_value AOS_RUNTIME fake
    echo "AOS_RUNTIME=fake (scripted model). Run 'make up' to apply."
    ;;
  real)
    key=$(env_value OPENAI_API_KEY)
    if [ -z "$key" ]; then
      # A terminal we can actually open (not just a /dev/tty node), e.g. not in CI.
      (exec </dev/tty) 2>/dev/null || { echo "OPENAI_API_KEY is not set in .env" >&2; exit 1; }
      read -r -s -p "OpenAI API key (input hidden): " key </dev/tty
      echo
      [ -n "$key" ] || { echo "No key given" >&2; exit 1; }
      set_value OPENAI_API_KEY "$key"
    fi

    env_model=$(env_value OPENAI_MODEL)
    model=${MODEL:-${env_model:-$DEFAULT_MODEL}}
    read -r list_in list_out <<<"$(list_prices "$model") "
    # A model we know uses its list price (so stale values in .env are replaced). Otherwise .env's prices are
    # kept, but only when they were set for this same model.
    env_in="" env_out=""
    if [ "$model" = "$env_model" ]; then
      env_in=$(env_value AOS_MODEL_PRICE_IN_PER_MTOK)
      env_out=$(env_value AOS_MODEL_PRICE_OUT_PER_MTOK)
    fi
    price_in=${PRICE_IN:-${list_in:-$env_in}}
    price_out=${PRICE_OUT:-${list_out:-$env_out}}
    if [ -z "$price_in" ] || [ -z "$price_out" ]; then
      echo "No list price known for $model: run again with PRICE_IN=<usd> PRICE_OUT=<usd> (per million tokens)" >&2
      exit 1
    fi

    set_value OPENAI_MODEL "$model"
    set_value AOS_MODEL_PRICE_IN_PER_MTOK "$price_in"
    set_value AOS_MODEL_PRICE_OUT_PER_MTOK "$price_out"
    [ -n "$(env_value AOS_MODEL_PROVIDER)" ] || set_value AOS_MODEL_PROVIDER openai
    set_value AOS_RUNTIME langgraph
    echo "Real model: $model, USD $price_in in / $price_out out per million tokens (OPENAI_API_KEY from .env)."
    ;;
  *)
    echo "usage: $0 real|fake" >&2
    exit 2
    ;;
esac
