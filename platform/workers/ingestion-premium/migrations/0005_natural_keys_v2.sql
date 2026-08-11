-- Phase 6 F0-E — contract-v2 natural keys for primary, revisions, and the
-- already-seeded change feed.  Each new key adds source discriminators that
-- the former global KEY_FIELDS sweep omitted; malformed rows retain their
-- legacy key and will use SHA-256 fallback when next ingested by the Worker.

UPDATE jquants_records
SET natural_key = CASE dataset
    WHEN 'equities_investor_types' THEN json_object(
        'PubDate', json_extract(payload, '$.PubDate'),
        'Section', json_extract(payload, '$.Section'))
    WHEN 'fins_dividend' THEN json_object(
        'Code', json_extract(payload, '$.Code'),
        'RefNo', COALESCE(json_extract(payload, '$.RefNo'), json_extract(payload, '$.CARefNo')))
    WHEN 'fins_earnings_date' THEN json_object(
        'Code', json_extract(payload, '$.Code'),
        'PubDate', json_extract(payload, '$.PubDate'),
        'SchDate', json_extract(payload, '$.SchDate'))
    WHEN 'markets_margin_alert' THEN json_object(
        'AppDate', json_extract(payload, '$.AppDate'),
        'Code', json_extract(payload, '$.Code'),
        'PubDate', json_extract(payload, '$.PubDate'))
    WHEN 'markets_short_ratio' THEN json_object(
        'Date', json_extract(payload, '$.Date'),
        'S33', json_extract(payload, '$.S33'))
    WHEN 'markets_short_sale_report' THEN json_object(
        'CalcDate', json_extract(payload, '$.CalcDate'),
        'Code', json_extract(payload, '$.Code'),
        'DICName', json_extract(payload, '$.DICName'),
        'DiscDate', json_extract(payload, '$.DiscDate'),
        'FundName', json_extract(payload, '$.FundName'))
    WHEN 'edinet_major_shareholders' THEN json_object(
        'Code', json_extract(payload, '$.Code'), 'DocId', json_extract(payload, '$.DocId'))
    WHEN 'edinet_cross_shareholdings' THEN json_object(
        'Code', json_extract(payload, '$.Code'), 'DocId', json_extract(payload, '$.DocId'))
    WHEN 'edinet_large_volume_shareholders' THEN json_object(
        'Code', json_extract(payload, '$.Code'), 'DocId', json_extract(payload, '$.DocId'))
    ELSE natural_key
END
WHERE dataset IN (
    'equities_investor_types', 'fins_dividend', 'fins_earnings_date',
    'markets_margin_alert', 'markets_short_ratio', 'markets_short_sale_report',
    'edinet_major_shareholders', 'edinet_cross_shareholdings',
    'edinet_large_volume_shareholders'
);

UPDATE jquants_records_revisions
SET natural_key = CASE dataset
    WHEN 'equities_investor_types' THEN json_object('PubDate', json_extract(payload, '$.PubDate'), 'Section', json_extract(payload, '$.Section'))
    WHEN 'fins_dividend' THEN json_object('Code', json_extract(payload, '$.Code'), 'RefNo', COALESCE(json_extract(payload, '$.RefNo'), json_extract(payload, '$.CARefNo')))
    WHEN 'fins_earnings_date' THEN json_object('Code', json_extract(payload, '$.Code'), 'PubDate', json_extract(payload, '$.PubDate'), 'SchDate', json_extract(payload, '$.SchDate'))
    WHEN 'markets_margin_alert' THEN json_object('AppDate', json_extract(payload, '$.AppDate'), 'Code', json_extract(payload, '$.Code'), 'PubDate', json_extract(payload, '$.PubDate'))
    WHEN 'markets_short_ratio' THEN json_object('Date', json_extract(payload, '$.Date'), 'S33', json_extract(payload, '$.S33'))
    WHEN 'markets_short_sale_report' THEN json_object('CalcDate', json_extract(payload, '$.CalcDate'), 'Code', json_extract(payload, '$.Code'), 'DICName', json_extract(payload, '$.DICName'), 'DiscDate', json_extract(payload, '$.DiscDate'), 'FundName', json_extract(payload, '$.FundName'))
    WHEN 'edinet_major_shareholders' THEN json_object('Code', json_extract(payload, '$.Code'), 'DocId', json_extract(payload, '$.DocId'))
    WHEN 'edinet_cross_shareholdings' THEN json_object('Code', json_extract(payload, '$.Code'), 'DocId', json_extract(payload, '$.DocId'))
    WHEN 'edinet_large_volume_shareholders' THEN json_object('Code', json_extract(payload, '$.Code'), 'DocId', json_extract(payload, '$.DocId'))
    ELSE natural_key
END
WHERE dataset IN ('equities_investor_types','fins_dividend','fins_earnings_date','markets_margin_alert','markets_short_ratio','markets_short_sale_report','edinet_major_shareholders','edinet_cross_shareholdings','edinet_large_volume_shareholders');

UPDATE ingestion_change_log
SET natural_key = CASE dataset
    WHEN 'equities_investor_types' THEN json_object('PubDate', json_extract(payload, '$.PubDate'), 'Section', json_extract(payload, '$.Section'))
    WHEN 'fins_dividend' THEN json_object('Code', json_extract(payload, '$.Code'), 'RefNo', COALESCE(json_extract(payload, '$.RefNo'), json_extract(payload, '$.CARefNo')))
    WHEN 'fins_earnings_date' THEN json_object('Code', json_extract(payload, '$.Code'), 'PubDate', json_extract(payload, '$.PubDate'), 'SchDate', json_extract(payload, '$.SchDate'))
    WHEN 'markets_margin_alert' THEN json_object('AppDate', json_extract(payload, '$.AppDate'), 'Code', json_extract(payload, '$.Code'), 'PubDate', json_extract(payload, '$.PubDate'))
    WHEN 'markets_short_ratio' THEN json_object('Date', json_extract(payload, '$.Date'), 'S33', json_extract(payload, '$.S33'))
    WHEN 'markets_short_sale_report' THEN json_object('CalcDate', json_extract(payload, '$.CalcDate'), 'Code', json_extract(payload, '$.Code'), 'DICName', json_extract(payload, '$.DICName'), 'DiscDate', json_extract(payload, '$.DiscDate'), 'FundName', json_extract(payload, '$.FundName'))
    WHEN 'edinet_major_shareholders' THEN json_object('Code', json_extract(payload, '$.Code'), 'DocId', json_extract(payload, '$.DocId'))
    WHEN 'edinet_cross_shareholdings' THEN json_object('Code', json_extract(payload, '$.Code'), 'DocId', json_extract(payload, '$.DocId'))
    WHEN 'edinet_large_volume_shareholders' THEN json_object('Code', json_extract(payload, '$.Code'), 'DocId', json_extract(payload, '$.DocId'))
    ELSE natural_key
END
WHERE dataset IN ('equities_investor_types','fins_dividend','fins_earnings_date','markets_margin_alert','markets_short_ratio','markets_short_sale_report','edinet_major_shareholders','edinet_cross_shareholdings','edinet_large_volume_shareholders');
