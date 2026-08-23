.PHONY: install smoke test doctor scrub-check

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
export PATH := $(ROOT)/bin:$(HOME)/.local/bin:$(PATH)

install:
	./scripts/install.sh

smoke:
	./tests/smoke.sh

test:
	python3 -m pytest tests/ -q

doctor:
	wick doctor

scrub-check:
	./scripts/scrub-check.sh
