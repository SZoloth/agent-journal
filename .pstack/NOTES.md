# Agent Journal

The [README](../README.md) owns the entry format, install commands, and verification steps. Unit and adapter checks run with `python3 -B -m unittest -v`.

The CLI owns storage. The adapters translate lifecycle and PR events into the same CLI calls. A Markdown file per entry lets parallel writers publish independently. A stable ID makes an exact retry converge. Only the relevant hooks in each existing settings file were added.

## Rollout brief

1. Keep the writer local and make outward transfer explicit. Check that desktop MCP defaults to writing only and that review copies leave out journal metadata.
2. Start from installed client config, hook payloads, GitHub receipts, and the actual JSON-RPC requests. A client registration, a received event, and a saved note each prove a different step.
3. Reuse the CLI underneath Gemini hooks and desktop MCP. Record verified PR states and use a named source manifest for the release bundle. Review and test each change under Code Craft and pstack.
4. Verify through direct client startup, journal readback, a replay test, GitHub visibility readback, and a clean extraction of the code bundle.
5. Treat this as a private reporting system with a separate transfer step. NASA removes identifying details from aviation reports before dissemination. The National Archives ties each transfer to an identified accession and description. Keep code and data destinations separate and transfer one reviewed file by entry ID. [NASA confidentiality](https://asrs.arc.nasa.gov/overview/confidentiality.html) · [NARA transfer requests](https://www.archives.gov/files/transfer-request-general-information-rev.pdf)

## Automatic backup brief

1. Make failures and stale backups visible. A running agent or a mounted iCloud folder alone tells us little about recoverability.
2. Use the live agent state, journal manifests, local verification logs, iCloud upload state, and GitHub readback as evidence.
3. Use the macOS user LaunchAgent with the existing Keychain loader and timeout wrapper. Verify the encrypted image before publishing it. Reuse the image if the journal contents match.
4. Confirm a real launchd run wrote a fresh receipt with the entry count, a checksum, and both destinations verified. Keep the recovery passphrase out of the receipt.
5. Digital preservation checks the bytes at both the file and collection levels. Apply that by hashing entries before archiving and checking the encrypted copy at each destination. [Library of Congress data integrity guidance](https://www.loc.gov/programs/digital-collections-management/inventory-and-custody/data-integrity-management/)

## Terminal browser brief

Build a read-only `agent-journal browse` view that makes a previous entry easy to find. Start from the Markdown and its project, date, kind, and author fields. Reuse the journal's parser and sorting rules. Test search, preview, and filtering through the installed command in wide and narrow terminals. As with an archival finding aid, keep the tools for locating records separate from the records themselves. [National Archives finding aids](https://www.archives.gov/research/catalog/lcdrg/elements/finding-aid-source)
