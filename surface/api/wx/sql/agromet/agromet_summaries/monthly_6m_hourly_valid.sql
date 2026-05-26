WITH month_days AS (
    SELECT
        EXTRACT(MONTH FROM day) AS month
        ,EXTRACT(YEAR FROM day) AS year
        ,EXTRACT(DAY FROM (DATE_TRUNC('MONTH', day) + INTERVAL '1 MONTH' - INTERVAL '1 day')) AS days_in_month        
    FROM
    (SELECT generate_series('{{ start_date }}'::date, '{{ end_date }}'::date, '1 MONTH'::interval)::date AS day) AS days
)
,extended_month_days AS (
    SELECT
        CASE 
            WHEN month<=5 THEN 12+month
        END as month
        ,CASE 
            WHEN month<=5 THEN year-1
        END as year
        ,days_in_month
    FROM month_days
    WHERE month in (1,12)
    UNION ALL
    SELECT * FROM month_days
)
,aggreation_total_days AS (
    SELECT
        year
        ,SUM(days_in_month) AS total_days
    FROM extended_month_days
    WHERE month BETWEEN {{month}} AND {{month}}+5
    GROUP BY year
)
,daily_data AS (
    SELECT
        station_id 
        ,variable_id
        ,so.symbol AS sampling_operation
        ,DATE(datetime AT TIME ZONE '{{timezone}}') AS day
        ,COUNT(DISTINCT EXTRACT(HOUR FROM datetime AT TIME ZONE '{{timezone}}')) AS total_hours
        ,CASE so.symbol
            WHEN 'MIN' THEN MIN(min_value)
            WHEN 'MAX' THEN MAX(max_value)
            WHEN 'ACCUM' THEN SUM(sum_value)
            ELSE AVG(avg_value)
        END AS value
    FROM hourly_summary hs
    JOIN wx_variable vr ON vr.id = hs.variable_id
    JOIN wx_samplingoperation so ON so.id = vr.sampling_operation_id
    WHERE station_id = {{station_id}}
      AND variable_id IN ({{variable_ids}})
      AND datetime AT TIME ZONE '{{timezone}}' >= '{{ start_date }}'
      AND datetime AT TIME ZONE '{{timezone}}' < '{{ end_date }}'
    GROUP BY station_id, variable_id, sampling_operation, day
)
,hourly_validated_data AS (
    SELECT
        station_id
        ,variable_id
        ,sampling_operation
        ,day
        ,EXTRACT(DAY FROM day) AS day_of_month
        ,EXTRACT(MONTH FROM day) AS month
        ,EXTRACT(YEAR FROM day) AS year        
        ,value      
    FROM daily_data
    WHERE (100*total_hours) >= (100-{{max_hour_pct}})*24
)
,extended_data AS(
    SELECT
        station_id
        ,variable_id
        ,sampling_operation
        ,day
        ,day_of_month
        ,CASE 
            WHEN month<=5 THEN 12+month
        END as month
        ,CASE 
            WHEN month<=5 THEN year-1
        END as year
        ,value       
    FROM hourly_validated_data
    WHERE month in (1,12)
    UNION ALL
    SELECT * FROM hourly_validated_data
)
,daily_lagged_data AS (
    SELECT
        *
        ,day - LAG(day) OVER (PARTITION BY station_id, variable_id, year ORDER BY day) AS day_diff
    FROM extended_data
    WHERE year BETWEEN {{start_year}} AND {{end_year}} 
      AND month BETWEEN {{month}} AND {{month}}+5
)
,aggreated_data AS (
    SELECT
        st.name AS station
        ,variable_id
        ,year
        ,ROUND(
            CASE sampling_operation
                WHEN 'MIN' THEN MIN(value)::numeric
                WHEN 'MAX' THEN MAX(value)::numeric
                WHEN 'ACCUM' THEN SUM(value)::numeric
                ELSE AVG(value)::numeric
            END, 1
        ) AS value
        ,COUNT(DISTINCT CASE WHEN (day IS NOT NULL) THEN day END) AS "count"
        ,MAX(CASE WHEN (day_of_month >= ({{max_day_gap}}+1)) THEN day_diff ELSE NULL END) AS "max_day_diff"
    FROM daily_lagged_data dld
    JOIN wx_station st ON st.id = dld.station_id
    GROUP BY st.name, variable_id, year, sampling_operation
)
,aggregation_pct AS (
    SELECT
        station
        ,variable_id
        ,{{month}} AS "month"
        ,ad.year
        ,value AS "3-Aggregation"
        ,ROUND(((100*(CASE WHEN ("max_day_diff" <= ({{max_day_gap}}+1)) THEN "count" ELSE 0 END))::numeric/atd.total_days::numeric),1) AS "Aggregation (% of days)"
    FROM aggreated_data ad
    LEFT JOIN aggreation_total_days atd ON atd.year=ad.year
)
SELECT
    station
    ,variable_id
    ,year
    ,month
    ,CASE WHEN "Aggregation (% of days)" >= (100-{{max_day_pct}}) THEN "3-Aggregation" ELSE NULL END AS "3-Aggregation"
    ,"Aggregation (% of days)"
FROM aggregation_pct
ORDER BY year