# MinerU License and Compatibility Review

Date: 2026-09-04  
Status: `PENDING` / optional provider only

## Version and source

- PyPI package observed: `mineru==3.4.5`.
- Repository: https://github.com/opendatalab/MinerU
- Observed master commit: `4fe4bde114a23ee5dd637eae99b767f4669bf58c`.
- Package metadata declares `requires-python = >=3.10,<3.14`.

## License

MinerU uses the [MinerU Open Source License](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md): Apache License 2.0 plus additional terms. The additional terms include:

1. Commercial use is allowed without a separate license until a consolidated
   threshold is crossed: more than 100 million monthly active users or more
   than USD 20 million monthly revenue.
2. Online services based on MinerU must clearly and prominently state that
   MinerU is used in the relevant interface or public documentation.
3. Rights terminate automatically if a required separate commercial license
   is not obtained or the attribution obligation is not met.

This is not recorded as a plain Apache-2.0 dependency. A product/legal review
is required before making it mandatory in a distributed or online service.

## Compatibility

Upstream documents PDF, image, DOCX, PPTX, and XLSX support, with pipeline,
engine, and HTTP-client backends. Its current README notes Windows support but
limits Windows versions to Python 3.10–3.12 because of the `ray` dependency.
This project is running Python 3.14.6, so installing the current package into
the Docling environment is not a valid test.

## Integration option

The module reserves `MinerUParser` as an explicit adapter. It currently:

- reports availability only when the package or CLI is present;
- raises a structured `PARSER_UNAVAILABLE`/pending error when unavailable;
- does not silently invoke MinerU as a fallback;
- does not claim to have parsed a document.

The production option is to test MinerU in a separate Python 3.12 environment
on D:, retain its output and version in the manifest, then compare its
canonical mapping against Docling on a reviewed complex-PDF corpus. That work
is outside this Round 1 result.

## Local result

MinerU was not installed or executed in Round 1. This is intentional and
recorded as `PENDING`, not `INTEGRATED`. Docling remains the only active parser
provider.

