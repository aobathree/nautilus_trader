"""
J-Quants (JPX official data API, V2) integration adapter.

EOD/historical data only — provides an `InstrumentProvider`, a request-only
`LiveMarketDataClient`, and an ETL CLI (``scripts/jquants_etl.py``) which
writes to a `ParquetDataCatalog` for backtesting.
"""
