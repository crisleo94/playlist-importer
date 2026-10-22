#!/bin/bash
set -e

mkdir -p /app/staticfiles
chown -R appuser:appuser /app/staticfiles

exec gosu appuser "$@"
