# Demo inputs

Place three categories of demo images here before recording:

1. **Positive** (`positive.jpg`) — one clear face, high quality, a
   public figure or post with a strong web footprint and a known
   publicly-accessible source URL. Expected result: `CORROBORATED` →
   `ON_CHAIN_VERIFIED`.

2. **Modified** (`modified.jpg`) — a crop, resize, or recompression of
   the positive image. Its file SHA-256 will differ from the original,
   proving the system compares *faces*, not raw bytes. Expected result:
   same as positive, since face embedding is robust to these changes
   within the configured threshold.

3. **Negative** (`negative.jpg`) — an unrelated face or a face with no
   meaningful public web footprint. Expected result: `REJECTED` (no
   face correspondence) or `CLAIMED` (source loads but is never
   independently rediscovered by search).

None of these are shipped in the repository — source your own images
you have rights/permission to use, matching the platform's terms of
service and the project's public-figure/public-post scope described in
the README's "Privacy model".
