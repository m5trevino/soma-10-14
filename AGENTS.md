# Droid Constraints
- Do not use file-reading, file-searching, or file-writing tools upon session startup.
- Always operate strictly in a passive text-conversation mode.
- Wait for explicit written permission from the user before interacting with the local file system or repository workspace.

# READ FIRST

`GROUND_TRUTH.md` in this directory is required reading before any change to
this project. It records what the pipeline is *designed* to do (declared in
`soma/soma_template.sql`) versus what the running code currently does, and it
lists five invariants that must not be broken.

The short version: instructions live in the `stage_instructions` table and each
stage reads its own view. The running code instead reads markdown from disk and
concatenates it into a chat message. That is a regression, not the design. Do
not "fix" the pipeline by improving prompts.

If a proposed change breaks an invariant in `GROUND_TRUTH.md`, stop and say so
rather than proceeding.
