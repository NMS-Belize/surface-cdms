-- Total number of days for each season and year
WITH RECURSIVE month_days AS (
    SELECT
        EXTRACT(MONTH FROM day) AS month,
        EXTRACT(YEAR FROM day) AS year,        
        EXTRACT(DAY FROM (DATE_TRUNC('MONTH', day) + INTERVAL '1 MONTH' - INTERVAL '1 day')) AS days_in_month        
    FROM
    (SELECT generate_series('{{ start_date }}'::date, '{{ end_date }}'::date, '1 MONTH'::interval)::date AS day) AS days
)
,hourly_data AS (
    SELECT
        station_id 
        ,datetime AT TIME ZONE '{{timezone}}' AS datetime
        ,DATE(datetime AT TIME ZONE '{{timezone}}') AS day
        ,EXTRACT(DAY FROM datetime AT TIME ZONE '{{timezone}}') AS day_of_month
        ,EXTRACT(MONTH FROM datetime AT TIME ZONE '{{timezone}}') AS month
        ,EXTRACT(YEAR FROM datetime AT TIME ZONE '{{timezone}}') AS year        
        ,max_value >= {{threshold}} AS is_humid_h
        ,max_value > {{threshold}} AS is_rh_above_h
        ,min_value < {{threshold}} AS is_rh_below_h
    FROM hourly_summary hs
    JOIN wx_variable vr ON vr.id = hs.variable_id
    WHERE station_id = {{station_id}}
      AND vr.symbol = 'RH'
      AND datetime AT TIME ZONE '{{timezone}}' >= '{{ start_date }}'
      AND datetime AT TIME ZONE '{{timezone}}' < '{{ end_date }}'
)
,hourly_lagged_data AS (
    SELECT
        station_id
        ,datetime
        ,day
        ,day_of_month
        ,month
        ,year
        ,is_humid_h
        ,is_rh_above_h
        ,is_rh_below_h        
        ,EXTRACT(HOUR FROM (datetime - LAG(datetime) OVER (PARTITION BY station_id, year ORDER BY datetime)))-1 AS hour_gap
    FROM hourly_data
    WHERE year BETWEEN {{start_year}} AND {{end_year}}  
)
,humid_seq_calc AS (
    SELECT
        station_id
        ,year
        ,month
        ,UNNEST(ARRAY_AGG(datetime ORDER BY datetime)) AS datetime
        ,UNNEST(ARRAY_AGG(day ORDER BY datetime)) AS day
        ,UNNEST(ARRAY_AGG(day_of_month ORDER BY datetime)) AS day_of_month
        ,UNNEST(ARRAY_AGG(is_humid_h ORDER BY datetime)) AS is_humid_h
        ,UNNEST(ARRAY_AGG(is_rh_above_h ORDER BY datetime)) AS is_rh_above_h
        ,UNNEST(ARRAY_AGG(is_rh_below_h ORDER BY datetime)) AS is_rh_below_h       
        ,UNNEST(ARRAY_AGG(hour_gap ORDER BY datetime)) AS hour_gap
        ,UNNEST(consecutive_flag_calc(
            ARRAY_AGG(is_humid_h ORDER BY datetime),
            ARRAY_AGG(hour_gap > 0 ORDER BY datetime)
        )) AS "humid_seq"
    FROM hourly_lagged_data
    GROUP BY station_id, year, month
)
,daily_lagged_data AS (
    SELECT
        station_id
        ,day
        ,day - 1 - LAG(day) OVER (PARTITION BY station_id, year ORDER BY day) AS day_gap    
    FROM (
        SELECT
            station_id 
            ,day
            ,year
            ,MAX(hour_gap)
        FROM humid_seq_calc hsc
        GROUP BY station_id, year, day
        ORDER BY station_id, year, day
    ) AS daily_agg
    WHERE year BETWEEN {{start_year}} AND {{end_year}}  
)
,aggreated_data AS (
    SELECT
        st.name AS station
        ,year
        ,month
        ,MAX(COALESCE("humid_seq", 0)) AS "humid_seq"
        ,COUNT(*) FILTER (WHERE is_rh_above_h) AS "above"
        ,COUNT(*) FILTER (WHERE is_rh_below_h) AS "below"
        ,COUNT(DISTINCT hsc.day) FILTER( WHERE hsc.day IS NOT NULL) AS "count"
        ,MAX(COALESCE(day_gap, 0)) FILTER(WHERE day_of_month > {{max_day_gap}}) AS "max_day_gap"
    FROM humid_seq_calc hsc
    JOIN wx_station st ON st.id = hsc.station_id
    LEFT JOIN daily_lagged_data dls ON dls.station_id = hsc.station_id AND dls.day = hsc.day
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
                    WHEN 'Longest Sequence' THEN ROUND("humid_seq"::numeric,2)::text
                    WHEN 'Below' THEN ROUND("below"::numeric,2)::text
                    WHEN 'Above' THEN ROUND("above"::numeric,2)::text
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
                    WHEN 'Longest Sequence' THEN ROUND("humid_seq"::numeric,2)::text
                    WHEN 'Below' THEN ROUND("below"::numeric,2)::text
                    WHEN 'Above' THEN ROUND("above"::numeric,2)::text
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
                    WHEN 'Longest Sequence' THEN ROUND("humid_seq"::numeric,2)::text
                    WHEN 'Below' THEN ROUND("below"::numeric,2)::text
                    WHEN 'Above' THEN ROUND("above"::numeric,2)::text
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
                    WHEN 'Longest Sequence' THEN ROUND("humid_seq"::numeric,2)::text
                    WHEN 'Below' THEN ROUND("below"::numeric,2)::text
                    WHEN 'Above' THEN ROUND("above"::numeric,2)::text
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
                    WHEN 'Longest Sequence' THEN ROUND("humid_seq"::numeric,2)::text
                    WHEN 'Below' THEN ROUND("below"::numeric,2)::text
                    WHEN 'Above' THEN ROUND("above"::numeric,2)::text
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
                    WHEN 'Longest Sequence' THEN ROUND("humid_seq"::numeric,2)::text
                    WHEN 'Below' THEN ROUND("below"::numeric,2)::text
                    WHEN 'Above' THEN ROUND("above"::numeric,2)::text
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
                    WHEN 'Longest Sequence' THEN ROUND("humid_seq"::numeric,2)::text
                    WHEN 'Below' THEN ROUND("below"::numeric,2)::text
                    WHEN 'Above' THEN ROUND("above"::numeric,2)::text
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
                    WHEN 'Longest Sequence' THEN ROUND("humid_seq"::numeric,2)::text
                    WHEN 'Below' THEN ROUND("below"::numeric,2)::text
                    WHEN 'Above' THEN ROUND("above"::numeric,2)::text
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
                    WHEN 'Longest Sequence' THEN ROUND("humid_seq"::numeric,2)::text
                    WHEN 'Below' THEN ROUND("below"::numeric,2)::text
                    WHEN 'Above' THEN ROUND("above"::numeric,2)::text
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
                    WHEN 'Longest Sequence' THEN ROUND("humid_seq"::numeric,2)::text
                    WHEN 'Below' THEN ROUND("below"::numeric,2)::text
                    WHEN 'Above' THEN ROUND("above"::numeric,2)::text
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
                    WHEN 'Longest Sequence' THEN ROUND("humid_seq"::numeric,2)::text
                    WHEN 'Below' THEN ROUND("below"::numeric,2)::text
                    WHEN 'Above' THEN ROUND("above"::numeric,2)::text
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
                    WHEN 'Longest Sequence' THEN ROUND("humid_seq"::numeric,2)::text
                    WHEN 'Below' THEN ROUND("below"::numeric,2)::text
                    WHEN 'Above' THEN ROUND("above"::numeric,2)::text
                    ELSE NULL
                END        
        END
    END) AS "DEC"
    ,MAX(CASE WHEN ad.month = 12 THEN
        ROUND(100*("count"::numeric/days_in_month::numeric),2)
    END) AS "DEC (% of days)"        
FROM aggreated_data ad
LEFT JOIN month_days md ON md.year=ad.year AND md.month=ad.month
CROSS JOIN (VALUES ('Above'), ('Below'), ('Longest Sequence')) AS products(product)
GROUP BY station, product, ad.year
ORDER BY station, product, year;