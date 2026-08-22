.PHONY: install smoke doctor scrub-check

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
export PATH := $(ROOT)/bin:$(HOME)/.local/bin:$(PATH)

install:
	./scripts/install.sh

smoke:
	./tests/smoke.sh

doctor:
	wick doctor

scrub-check:
	./scripts/scrub-check.sh
