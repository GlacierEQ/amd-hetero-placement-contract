# Issue contract — Heterogeneous Placement Contract

## Problem
Data movement, network synchronization, memory hierarchy, and software integration.

## Desired outcome
A bounded, open, testable implementation of **Heterogeneous Placement Contract** that demonstrates Expose a placement descriptor (latency, energy, memory locality, privacy) and a deterministic placer that returns a bound execution target or explicit refusal.

## Non-goals
- AMD affiliation or proprietary integration
- Portfolio-wide scale/performance claims
- UI marketing site

## Acceptance
1. Mechanism module implements allow + refuse with structured receipts
2. pytest behavioral suite green
3. operate.py cold-start produces JSON receipt
4. Non-affiliation disclaimer preserved
