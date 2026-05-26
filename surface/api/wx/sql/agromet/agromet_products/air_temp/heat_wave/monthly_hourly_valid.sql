-- Total number of days for each season and year
WITH RECURSIVE month_days AS (
    SELECT
        EXTRACT(MONTH FROM day) AS month,
        EXTRACT(YEAR FROM day) AS year,        
        EXTRACT(DAY FROM (DATE_TRUNC('MONTH', day) + INTERVAL '1 MONTH' - INTERVAL '1 day')) AS days_in_month        
    FROM
    (SELECT generate_series('{{ start_date }}'::date, '{{ end_date }}'::date, '1 MONTH'::interval)::date AS day) AS days
)
-- Daily Data from Hourly Summary
-- ,hourly_data AS (
--     SELECT
--         station_id 
--         ,DATE(datetime AT TIME ZONE '{{timezone}}') AS day
--         ,EXTRACT(HOUR FROM datetime AT TIME ZONE '{{timezone}}') AS hour
--         ,min_value
--         ,max_value
--         ,avg_value
--         ,sum_value
--     FROM hourly_summary hs
--     JOIN wx_variable vr ON vr.id = hs.variable_id
--     WHERE station_id = {{station_id}}
--       AND vr.symbol = 'TEMP'
--       AND datetime AT TIME ZONE '{{timezone}}' >= '{{ start_date }}'
--       AND datetime AT TIME ZONE '{{timezone}}' < '{{ end_date }}'
-- )
-- ,daily_data AS (
--     SELECT
--         station_id
--         ,day
--         ,day_of_month
--         ,month
--         ,year
--         ,total_hours
--         ,tmax
--     FROM (
--         SELECT
--             station_id
--             ,day
--             ,EXTRACT(DAY FROM day) AS day_of_month
--             ,EXTRACT(MONTH FROM day) AS month
--             ,EXTRACT(YEAR FROM day) AS year        
--             ,COUNT(DISTINCT hour) AS total_hours
--             ,MAX(max_value) AS tmax
--         FROM hourly_data
--         GROUP BY station_id, day        
--     ) ddr
--     WHERE 100*(total_hours::numeric/24) > (100-{{max_hour_pct}})
-- )
-- Daily Data from Daily Summary
,daily_data AS (
    SELECT
        station_id 
        ,day
        ,EXTRACT(DAY FROM day) AS day_of_month
        ,EXTRACT(MONTH FROM day) AS month
        ,EXTRACT(YEAR FROM day) AS year
        ,max_value AS tmax
    FROM daily_summary ds
    JOIN wx_variable vr ON vr.id = ds.variable_id
    WHERE station_id = {{station_id}}
      AND vr.symbol = 'TEMP'
      AND '{{ start_date }}' <= day AND day < '{{ end_date }}'
)
,heat_wave_data AS (
    SELECT
        station_id
        ,day
        ,day_of_month
        ,month
        ,year
        ,CASE WHEN tmax > {{threshold}} THEN TRUE ELSE FALSE END AS is_hot_day
    FROM daily_data
)
,daily_lagged_data AS (
    SELECT
        *
        ,day - 1 - LAG(day) OVER (PARTITION BY station_id, year ORDER BY day) AS day_gap
    FROM heat_wave_data  
    WHERE year BETWEEN {{start_year}} AND {{end_year}}
)
,heat_wave_calc AS (
    SELECT
        station_id
        ,year
        ,UNNEST(ARRAY_AGG(day ORDER BY day)) AS day
        ,UNNEST(ARRAY_AGG(day_of_month ORDER BY day)) AS day_of_month
        ,UNNEST(ARRAY_AGG(month ORDER BY day)) AS month
        ,UNNEST(ARRAY_AGG(is_hot_day ORDER BY day)) AS is_hot_day
        ,UNNEST(ARRAY_AGG(day_gap ORDER BY day)) AS day_gap
        ,UNNEST(consecutive_flag_calc(
            ARRAY_AGG(is_hot_day ORDER BY day),
            ARRAY_AGG(day_gap > 0 ORDER BY day)
        )) AS "hot_seq"
    FROM daily_lagged_data
    GROUP BY station_id, year, month
)
,aggreated_data AS (
    SELECT
        st.name AS station
        ,year
        ,month
        ,COALESCE(MAX("hot_seq") FILTER (WHERE "hot_seq" >= {{heat_wave_window}}),0) AS "max_seq"
        ,COUNT(*) FILTER (WHERE "hot_seq" = {{heat_wave_window}}) AS "heat_wave_events"
        ,COUNT(*) FILTER (WHERE is_hot_day) AS "hot_days"
        ,COUNT(DISTINCT day) FILTER(WHERE day IS NOT NULL) AS "count"
        ,MAX(COALESCE(day_gap)) FILTER(WHERE day_of_month > {{max_day_gap}}) AS "max_day_gap"
    FROM heat_wave_calc hwc
    JOIN wx_station st ON st.id = hwc.station_id
    GROUP BY st.name, year, month
)
SELECT
    station
    ,product
    ,ad.year
    ,MAX(CASE WHEN ad.month = 1 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE
                CASE product
                    WHEN 'longest heat wave duration' THEN ROUND("max_seq"::numeric,2)::text
                    WHEN 'number heat wave events' THEN ROUND("heat_wave_events"::numeric,2)::text
                    WHEN 'number of hot days' THEN ROUND("hot_days"::numeric,2)::text
                    ELSE NULL
                END
        END
    END) AS "JAN"
    ,MAX(CASE WHEN ad.month = 1 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "JAN (% of days)"
    ,MAX(CASE WHEN ad.month = 2 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE
                CASE product
                    WHEN 'longest heat wave duration' THEN ROUND("max_seq"::numeric,2)::text
                    WHEN 'number heat wave events' THEN ROUND("heat_wave_events"::numeric,2)::text
                    WHEN 'number of hot days' THEN ROUND("hot_days"::numeric,2)::text
                    ELSE NULL
                END
        END
    END) AS "FEB"
    ,MAX(CASE WHEN ad.month = 2 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "FEB (% of days)"    
    ,MAX(CASE WHEN ad.month = 3 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE
                CASE product
                    WHEN 'longest heat wave duration' THEN ROUND("max_seq"::numeric,2)::text
                    WHEN 'number heat wave events' THEN ROUND("heat_wave_events"::numeric,2)::text
                    WHEN 'number of hot days' THEN ROUND("hot_days"::numeric,2)::text
                    ELSE NULL
                END
        END
    END) AS "FEB"
    ,MAX(CASE WHEN ad.month = 3 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "MAR (% of days)"
    ,MAX(CASE WHEN ad.month = 4 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE
                CASE product
                    WHEN 'longest heat wave duration' THEN ROUND("max_seq"::numeric,2)::text
                    WHEN 'number heat wave events' THEN ROUND("heat_wave_events"::numeric,2)::text
                    WHEN 'number of hot days' THEN ROUND("hot_days"::numeric,2)::text
                    ELSE NULL
                END
        END
    END) AS "APR"
    ,MAX(CASE WHEN ad.month = 4 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "APR (% of days)"
    ,MAX(CASE WHEN ad.month = 5 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE
                CASE product
                    WHEN 'longest heat wave duration' THEN ROUND("max_seq"::numeric,2)::text
                    WHEN 'number heat wave events' THEN ROUND("heat_wave_events"::numeric,2)::text
                    WHEN 'number of hot days' THEN ROUND("hot_days"::numeric,2)::text
                    ELSE NULL
                END
        END
    END) AS "MAY"
    ,MAX(CASE WHEN ad.month = 5 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "MAY (% of days)"
    ,MAX(CASE WHEN ad.month = 6 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE
                CASE product
                    WHEN 'longest heat wave duration' THEN ROUND("max_seq"::numeric,2)::text
                    WHEN 'number heat wave events' THEN ROUND("heat_wave_events"::numeric,2)::text
                    WHEN 'number of hot days' THEN ROUND("hot_days"::numeric,2)::text
                    ELSE NULL
                END
        END
    END) AS "JUN"
    ,MAX(CASE WHEN ad.month = 6 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "JUN (% of days)"
    ,MAX(CASE WHEN ad.month = 7 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE
                CASE product
                    WHEN 'longest heat wave duration' THEN ROUND("max_seq"::numeric,2)::text
                    WHEN 'number heat wave events' THEN ROUND("heat_wave_events"::numeric,2)::text
                    WHEN 'number of hot days' THEN ROUND("hot_days"::numeric,2)::text
                    ELSE NULL
                END
        END
    END) AS "JUL"
    ,MAX(CASE WHEN ad.month = 7 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "JUL (% of days)"  
    ,MAX(CASE WHEN ad.month = 8 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE
                CASE product
                    WHEN 'longest heat wave duration' THEN ROUND("max_seq"::numeric,2)::text
                    WHEN 'number heat wave events' THEN ROUND("heat_wave_events"::numeric,2)::text
                    WHEN 'number of hot days' THEN ROUND("hot_days"::numeric,2)::text
                    ELSE NULL
                END
        END
    END) AS "AUG"
    ,MAX(CASE WHEN ad.month = 8 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "AUG (% of days)"  
    ,MAX(CASE WHEN ad.month = 9 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE
                CASE product
                    WHEN 'longest heat wave duration' THEN ROUND("max_seq"::numeric,2)::text
                    WHEN 'number heat wave events' THEN ROUND("heat_wave_events"::numeric,2)::text
                    WHEN 'number of hot days' THEN ROUND("hot_days"::numeric,2)::text
                    ELSE NULL
                END
        END
    END) AS "SEP"
    ,MAX(CASE WHEN ad.month = 9 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "SEP (% of days)"
    ,MAX(CASE WHEN ad.month = 10 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE
                CASE product
                    WHEN 'longest heat wave duration' THEN ROUND("max_seq"::numeric,2)::text
                    WHEN 'number heat wave events' THEN ROUND("heat_wave_events"::numeric,2)::text
                    WHEN 'number of hot days' THEN ROUND("hot_days"::numeric,2)::text
                    ELSE NULL
                END
        END
    END) AS "OCT"
    ,MAX(CASE WHEN ad.month = 10 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "OCT (% of days)"    
    ,MAX(CASE WHEN ad.month = 11 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE
                CASE product
                    WHEN 'longest heat wave duration' THEN ROUND("max_seq"::numeric,2)::text
                    WHEN 'number heat wave events' THEN ROUND("heat_wave_events"::numeric,2)::text
                    WHEN 'number of hot days' THEN ROUND("hot_days"::numeric,2)::text
                    ELSE NULL
                END
        END
    END) AS "NOV"
    ,MAX(CASE WHEN ad.month = 11 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "NOV (% of days)"
    ,MAX(CASE WHEN ad.month = 12 THEN
        CASE 
            WHEN "max_day_gap" > {{max_day_gap}} THEN 'Gap Exceeded'
            WHEN ROUND(100*("count"::numeric/days_in_month::numeric),2) < (100-{{max_day_pct}}) THEN 'Pct Exceeded'
            ELSE
                CASE product
                    WHEN 'longest heat wave duration' THEN ROUND("max_seq"::numeric,2)::text
                    WHEN 'number heat wave events' THEN ROUND("heat_wave_events"::numeric,2)::text
                    WHEN 'number of hot days' THEN ROUND("hot_days"::numeric,2)::text
                    ELSE NULL
                END
        END
    END) AS "DEC"
    ,MAX(CASE WHEN ad.month = 12 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "DEC (% of days)"              
FROM aggreated_data ad
LEFT JOIN month_days md ON md.year=ad.year AND md.month = ad.month
CROSS JOIN (VALUES ('number of hot days'), ('longest heat wave duration'), ('number heat wave events')) AS products(product)
GROUP BY station, product, ad.year
ORDER BY station, product, year