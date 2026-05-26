-- Total number of days for each season and year
WITH month_days AS (
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
--       AND vr.symbol = 'PRECIP'
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
--         ,precip
--     FROM (
--         SELECT
--             station_id
--             ,day
--             ,EXTRACT(DAY FROM day) AS day_of_month
--             ,EXTRACT(MONTH FROM day) AS month
--             ,EXTRACT(YEAR FROM day) AS year        
--             ,COUNT(DISTINCT hour) AS total_hours
--             ,SUM(sum_value) AS precip
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
        ,sum_value AS precip
    FROM daily_summary ds
    JOIN wx_variable vr ON vr.id = ds.variable_id
    WHERE station_id = {{station_id}}
      AND vr.symbol = 'PRECIP'
      AND '{{ start_date }}' <= day AND day < '{{ end_date }}'
)
,daily_lagged_data AS (
    SELECT
        *   
        ,day - 1 - LAG(day) OVER (PARTITION BY station_id, year ORDER BY day) AS day_gap
    FROM daily_data
    WHERE year BETWEEN {{start_year}} AND {{end_year}}  
)
,aggreated_data AS (
    SELECT
        st.name AS station
        ,year
        ,month
        ,COUNT(*) FILTER(WHERE precip > 25) AS "above_25"
        ,COUNT(*) FILTER(WHERE precip > 50) AS "above_50"
        ,COUNT(*) FILTER(WHERE precip > 84) AS "above_84"
        ,COUNT(*) FILTER(WHERE precip > 200) AS "above_200"
        ,COUNT(DISTINCT day) FILTER(WHERE day IS NOT NULL) AS "count"
        ,MAX(COALESCE(day_gap, 0)) FILTER(WHERE day_of_month > {{max_day_gap}}) AS "max_day_gap"
    FROM daily_lagged_data dld
    JOIN wx_station st ON st.id = dld.station_id
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
                    WHEN '25 mm Rainfall' THEN ROUND("above_25"::numeric,2)::text
                    WHEN '50 mm Rainfall' THEN ROUND("above_50"::numeric,2)::text
                    WHEN '84 mm Rainfall' THEN ROUND("above_84"::numeric,2)::text
                    WHEN '200 mm Rainfall' THEN ROUND("above_200"::numeric,2)::text                                
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
                    WHEN '25 mm Rainfall' THEN ROUND("above_25"::numeric,2)::text
                    WHEN '50 mm Rainfall' THEN ROUND("above_50"::numeric,2)::text
                    WHEN '84 mm Rainfall' THEN ROUND("above_84"::numeric,2)::text
                    WHEN '200 mm Rainfall' THEN ROUND("above_200"::numeric,2)::text                                
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
                    WHEN '25 mm Rainfall' THEN ROUND("above_25"::numeric,2)::text
                    WHEN '50 mm Rainfall' THEN ROUND("above_50"::numeric,2)::text
                    WHEN '84 mm Rainfall' THEN ROUND("above_84"::numeric,2)::text
                    WHEN '200 mm Rainfall' THEN ROUND("above_200"::numeric,2)::text                                
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
                    WHEN '25 mm Rainfall' THEN ROUND("above_25"::numeric,2)::text
                    WHEN '50 mm Rainfall' THEN ROUND("above_50"::numeric,2)::text
                    WHEN '84 mm Rainfall' THEN ROUND("above_84"::numeric,2)::text
                    WHEN '200 mm Rainfall' THEN ROUND("above_200"::numeric,2)::text                                
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
                    WHEN '25 mm Rainfall' THEN ROUND("above_25"::numeric,2)::text
                    WHEN '50 mm Rainfall' THEN ROUND("above_50"::numeric,2)::text
                    WHEN '84 mm Rainfall' THEN ROUND("above_84"::numeric,2)::text
                    WHEN '200 mm Rainfall' THEN ROUND("above_200"::numeric,2)::text                                
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
                    WHEN '25 mm Rainfall' THEN ROUND("above_25"::numeric,2)::text
                    WHEN '50 mm Rainfall' THEN ROUND("above_50"::numeric,2)::text
                    WHEN '84 mm Rainfall' THEN ROUND("above_84"::numeric,2)::text
                    WHEN '200 mm Rainfall' THEN ROUND("above_200"::numeric,2)::text                                
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
                    WHEN '25 mm Rainfall' THEN ROUND("above_25"::numeric,2)::text
                    WHEN '50 mm Rainfall' THEN ROUND("above_50"::numeric,2)::text
                    WHEN '84 mm Rainfall' THEN ROUND("above_84"::numeric,2)::text
                    WHEN '200 mm Rainfall' THEN ROUND("above_200"::numeric,2)::text                                
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
                    WHEN '25 mm Rainfall' THEN ROUND("above_25"::numeric,2)::text
                    WHEN '50 mm Rainfall' THEN ROUND("above_50"::numeric,2)::text
                    WHEN '84 mm Rainfall' THEN ROUND("above_84"::numeric,2)::text
                    WHEN '200 mm Rainfall' THEN ROUND("above_200"::numeric,2)::text                                
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
                    WHEN '25 mm Rainfall' THEN ROUND("above_25"::numeric,2)::text
                    WHEN '50 mm Rainfall' THEN ROUND("above_50"::numeric,2)::text
                    WHEN '84 mm Rainfall' THEN ROUND("above_84"::numeric,2)::text
                    WHEN '200 mm Rainfall' THEN ROUND("above_200"::numeric,2)::text                                
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
                    WHEN '25 mm Rainfall' THEN ROUND("above_25"::numeric,2)::text
                    WHEN '50 mm Rainfall' THEN ROUND("above_50"::numeric,2)::text
                    WHEN '84 mm Rainfall' THEN ROUND("above_84"::numeric,2)::text
                    WHEN '200 mm Rainfall' THEN ROUND("above_200"::numeric,2)::text                                
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
                    WHEN '25 mm Rainfall' THEN ROUND("above_25"::numeric,2)::text
                    WHEN '50 mm Rainfall' THEN ROUND("above_50"::numeric,2)::text
                    WHEN '84 mm Rainfall' THEN ROUND("above_84"::numeric,2)::text
                    WHEN '200 mm Rainfall' THEN ROUND("above_200"::numeric,2)::text                                
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
                    WHEN '25 mm Rainfall' THEN ROUND("above_25"::numeric,2)::text
                    WHEN '50 mm Rainfall' THEN ROUND("above_50"::numeric,2)::text
                    WHEN '84 mm Rainfall' THEN ROUND("above_84"::numeric,2)::text
                    WHEN '200 mm Rainfall' THEN ROUND("above_200"::numeric,2)::text                                
                    ELSE NULL
                END            
        END
    END) AS "DEC"
    ,MAX(CASE WHEN ad.month = 12 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "DEC (% of days)"        
FROM aggreated_data ad
LEFT JOIN month_days md ON md.year=ad.year AND md.month=ad.month
CROSS JOIN (VALUES ('25 mm Rainfall'), ('84 mm Rainfall'), ('200 mm Rainfall'), ('50 mm Rainfall')) AS products(product)
GROUP BY station, product, ad.year
ORDER BY station, product, year;