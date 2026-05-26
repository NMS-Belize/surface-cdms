WITH cte AS (
    SELECT
        vr.symbol
        ,MIN(ds.day) AS first_date
        ,MAX(ds.day) AS last_date
    FROM daily_summary ds
    JOIN wx_variable vr ON vr.id = ds.variable_id
    WHERE ds.station_id = 4
      AND vr.symbol IN ('TEMP','PRECIP', 'PRESSTN', 'WNDSPAVG', 'SOLARRAD', 'RH')
    GROUP BY vr.symbol
)
SELECT
    vrs.symbol
    ,cte.first_date
    ,cte.last_date
FROM (VALUES  ('TEMP'),('PRECIP'),('PRESSTN'),('WNDSPAVG'),('SOLARRAD'),('RH')) AS vrs(symbol)
LEFT JOIN cte ON cte.symbol = vrs.symbol