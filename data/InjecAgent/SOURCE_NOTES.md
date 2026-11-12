# InjecAgent

2108 collected records staged.

- collection/: unchanged copy of the complete collected dataset, including source snapshot, metadata and validation.
- cases/: one JSON file per normalized record; contents preserved without adding invented labels or outcomes. Match filenames to original IDs using ../test_index.csv.

Before execution: Adapt mock tools/environment and define outcome checks; create and review matched clean control. Base/enhanced records are attack variants, not clean/attacked pairs.
