#!/usr/bin/env bash
cd /home/vardhin/Documents/git/lexicon/lexicon-backend
exec .venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
