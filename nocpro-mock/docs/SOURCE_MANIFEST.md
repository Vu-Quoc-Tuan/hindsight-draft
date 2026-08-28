# Source Manifest

| Source | Role in docs | Verification status |
|---|---|---|
| `alarm_data(1).csv` | real alarm/chaining export profile | verified by parser |
| `topoIP-8zjkidh613ffzdck7jca5j6bdc.csv` | real IP adjacency topology export | verified by parser |
| `BaoCao_Attribute_Louvain_Chaining.docx` | NocPro Attribute/Louvain semantics | verified from supplied report |
| Chain `2214039` pasted sample | Golden Gray-box fixture | user-provided observed case |
| `image-djskfq...png` | visual multi-layer IT topology reference | visually inspected |
| `topoIT-*.zip` | future topoIT source | 7z signature; full schema unverified here |
| `alarm-*.zip` | future large alarm source | 7z signature; full schema unverified here |

## Frozen verified counts

```text
alarm_data:
  rows = 8714
  columns = 96
  unique_chaining_id = 2824
  singleton_chains = 2072
  singleton_pct = 73.3711
  max_chain_size = 1072
  max_chain_id = 6907125
  node_reference_fill_pct = 98.0606
  physical_lines = 26508

topoIP:
  rows = 201977
  columns = 16
  source_network_class_SITE_ROUTER_pct = 90.3860
```
