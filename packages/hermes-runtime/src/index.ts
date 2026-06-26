// Hermes Runtime Shim — the only package allowed to import the official Hermes
// SDK (ADR-0100). Runtime boot, profile selection, and registration land in
// slice #13.
export const HERMES_RUNTIME_PACKAGE = "@toee/hermes-runtime";
