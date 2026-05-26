WITH month_days AS (
    SELECT
        EXTRACT(MONTH FROM day) AS month,
        EXTRACT(YEAR FROM day) AS year,        
        EXTRACT(DAY FROM (DATE_TRUNC('MONTH', day) + INTERVAL '1 MONTH' - INTERVAL '1 day')) AS days_in_month
    FROM
    (SELECT generate_series('{{ start_date }}'::date, '{{ end_date }}'::date, '1 MONTH'::interval)::date AS day) AS days
)
,daily_data AS (
    SELECT
        station_id 
        ,vr.symbol AS variable
        ,day
        ,EXTRACT(DAY FROM day) AS day_of_month
        ,EXTRACT(MONTH FROM day) AS month
        ,EXTRACT(YEAR FROM day) AS year
        ,min_value AS tmin
        ,max_value AS tmax
    FROM daily_summary ds
    JOIN wx_variable vr ON vr.id = ds.variable_id
    WHERE station_id = {{station_id}}
      AND vr.symbol IN ('TEMP', 'TEMPMIN', 'TEMPMAX')
      AND day >= '{{ start_date }}' AND day < '{{ end_date }}'
)
,daily_lagged_data AS (
    SELECT
        *
        ,day - 1 - LAG(day) OVER (PARTITION BY station_id, variable, year ORDER BY day) AS day_gap
    FROM daily_data
    WHERE year BETWEEN {{start_year}} AND {{end_year}}  
)
,aggreated_data AS (
    SELECT
        st.name AS station
        ,variable
        ,year
        ,month
        ,MIN(tmin) AS "min"
        ,MAX(tmax) AS "max"
        ,COUNT(DISTINCT day) FILTER(WHERE day IS NOT NULL) AS "count"
        ,MAX(COALESCE(day_gap, 0)) FILTER(WHERE day_of_month > {{max_day_gap}}) AS "max_day_gap"
    FROM daily_lagged_data dld
    JOIN wx_station st ON st.id = dld.station_id
    GROUP BY st.name, variable, year, month
)
SELECT
    station
    ,variable || ' (MIN/MAX)' AS product
    ,ad.year
    ,MIN(CASE WHEN ad.month = 1 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("min"::numeric, 2)::text
        END
    END) AS "JAN_min"
    ,MAX(CASE WHEN ad.month = 1 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("max"::numeric, 2)::text
        END
    END) AS "JAN_max"
    ,MAX(CASE WHEN ad.month = 1 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "JAN (% of days)"
    ,MIN(CASE WHEN ad.month = 2 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("min"::numeric, 2)::text
        END
    END) AS "FEB_min"
    ,MAX(CASE WHEN ad.month = 2 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("max"::numeric, 2)::text
        END
    END) AS "FEB_max"
    ,MAX(CASE WHEN ad.month = 2 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "FEB (% of days)"    
    ,MIN(CASE WHEN ad.month = 3 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("min"::numeric, 2)::text
        END
    END) AS "FEB_min"
    ,MAX(CASE WHEN ad.month = 3 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("max"::numeric, 2)::text
        END
    END) AS "MAR_max"
    ,MAX(CASE WHEN ad.month = 3 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "MAR (% of days)"
    ,MIN(CASE WHEN ad.month = 4 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("min"::numeric, 2)::text
        END
    END) AS "APR_min"
    ,MAX(CASE WHEN ad.month = 4 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("max"::numeric, 2)::text
        END
    END) AS "APR_max"
    ,MAX(CASE WHEN ad.month = 4 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "APR (% of days)"
    ,MIN(CASE WHEN ad.month = 5 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("min"::numeric, 2)::text
        END
    END) AS "MAY_min"
    ,MAX(CASE WHEN ad.month = 5 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("max"::numeric, 2)::text
        END
    END) AS "MAY_max"
    ,MAX(CASE WHEN ad.month = 5 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "MAY (% of days)"
    ,MIN(CASE WHEN ad.month = 6 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("min"::numeric, 2)::text
        END
    END) AS "JUN_min"
    ,MAX(CASE WHEN ad.month = 6 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("max"::numeric, 2)::text
        END
    END) AS "JUN_max"
    ,MAX(CASE WHEN ad.month = 6 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "JUN (% of days)"
    ,MIN(CASE WHEN ad.month = 7 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("min"::numeric, 2)::text
        END
    END) AS "JUL_min"
    ,MAX(CASE WHEN ad.month = 7 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("max"::numeric, 2)::text
        END
    END) AS "JUL_max"
    ,MAX(CASE WHEN ad.month = 7 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "JUL (% of days)"  
    ,MIN(CASE WHEN ad.month = 8 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("min"::numeric, 2)::text
        END
    END) AS "AUG_min"
    ,MAX(CASE WHEN ad.month = 8 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("max"::numeric, 2)::text
        END
    END) AS "AUG_max"
    ,MAX(CASE WHEN ad.month = 8 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "AUG (% of days)"  
    ,MIN(CASE WHEN ad.month = 9 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("min"::numeric, 2)::text
        END
    END) AS "SEP_min"
    ,MAX(CASE WHEN ad.month = 9 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("max"::numeric, 2)::text
        END
    END) AS "SEP_max"
    ,MAX(CASE WHEN ad.month = 9 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "SEP (% of days)"
    ,MIN(CASE WHEN ad.month = 10 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("min"::numeric, 2)::text
        END
    END) AS "OCT_min"
    ,MAX(CASE WHEN ad.month = 10 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("max"::numeric, 2)::text
        END
    END) AS "OCT_max"
    ,MAX(CASE WHEN ad.month = 10 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "OCT (% of days)"    
    ,MIN(CASE WHEN ad.month = 11 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("min"::numeric, 2)::text
        END
    END) AS "NOV_min"
    ,MAX(CASE WHEN ad.month = 11 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("max"::numeric, 2)::text
        END
    END) AS "NOV_max"
    ,MAX(CASE WHEN ad.month = 11 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "NOV (% of days)"
    ,MIN(CASE WHEN ad.month = 12 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("min"::numeric, 2)::text
        END
    END) AS "DEC_min"
    ,MAX(CASE WHEN ad.month = 12 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE ROUND("max"::numeric, 2)::text
        END
    END) AS "DEC_max"
    ,MAX(CASE WHEN ad.month = 12 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "DEC (% of days)"
FROM aggreated_data ad
LEFT JOIN month_days md ON md.year = ad.year AND md.month = ad.month
GROUP BY station, variable, ad.year
ORDER BY station, product, year;