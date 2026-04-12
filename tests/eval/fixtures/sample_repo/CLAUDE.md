
<!-- LV_DCP managed section — do not edit manually -->
## LV_DCP Context Discipline (ОБЯЗАТЕЛЬНО)

**BLOCKING REQUIREMENT:** This project is indexed by LV_DCP. You MUST call `lvdcp_pack` BEFORE using Grep, Read, or any file exploration tool. This is not optional.

**EVERY task starts with lvdcp_pack:**

- Navigate: `lvdcp_pack(path="/Users/v.lukin/Nextcloud/lukinvit.tech/projects/LV_DCP/tests/eval/fixtures/sample_repo", query="your question", mode="navigate")`
- Edit: `lvdcp_pack(path="/Users/v.lukin/Nextcloud/lukinvit.tech/projects/LV_DCP/tests/eval/fixtures/sample_repo", query="task description", mode="edit")`

**Why:** The pack returns 2-20 KB of ranked files and symbols in <1 second. Without it, you grep-walk the entire repo (~1M+ tokens). The pack is 1000x cheaper and already knows the dependency graph.

**After receiving the pack:** Read only the top files from it. Do NOT grep the entire repo.
<!-- end LV_DCP managed section -->
