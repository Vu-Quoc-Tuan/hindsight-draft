# Contract Consumption

Canonical Input Contract is owned by `nocpro-chain-explain/contracts/v1`.

`nocpro-mock` SHALL:
1. validate its output against that version,
2. reject incompatible major versions,
3. never define a divergent canonical contract.

A generated/read-only local copy may be used for CI.
