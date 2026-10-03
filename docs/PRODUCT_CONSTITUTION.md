# Product Constitution

Linux Gaming Doctor is not a generic optimizer and not a launcher.

Its job is to:

1. collect facts without mutating the machine;
2. identify the narrowest failing boundary;
3. run controlled differential tests where safe;
4. classify the result as `REPAIRABLE`, `WORKAROUND`, `UPSTREAM_BUG`, `UNSUPPORTED_POLICY`, or `UNKNOWN`;
5. apply only evidence-backed repairs;
6. verify the effect;
7. roll back automatically when verification fails;
8. produce a privacy-safe report with reproducible evidence.

A diagnosis that proves the user's machine is healthy and the problem is upstream is considered a success.
