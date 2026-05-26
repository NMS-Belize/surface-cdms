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
            WHEN month<=2 THEN 12+month
        END as month
        ,CASE 
            WHEN month<=2 THEN year-1
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
    WHERE month BETWEEN {{month}} AND {{month}}+2
    GROUP BY year
)
,daily_data AS (
    SELECT
        station_id 
        ,variable_id
        ,so.symbol AS sampling_operation
        ,DATE(day) AS day
        ,EXTRACT(DAY FROM day) AS day_of_month
        ,EXTRACT(MONTH FROM day) AS month
        ,EXTRACT(YEAR FROM day) AS year
        ,CASE so.symbol
            WHEN 'MIN' THEN MIN(min_value)
            WHEN 'MAX' THEN MAX(max_value)
            WHEN 'ACCUM' THEN SUM(sum_value)
            ELSE AVG(avg_value)
        END AS value
    FROM daily_summary ds
    JOIN wx_variable vr ON vr.id = ds.variable_id
    JOIN wx_samplingoperation so ON so.id = vr.sampling_operation_id
    WHERE station_id = {{station_id}}
      AND variable_id IN ({{variable_ids}})
      AND day >= '{{ start_date }}'
      AND day < '{{ end_date }}'
    GROUP BY station_id, variable_id, sampling_operation, day, day_of_month, month, year
)
,extended_data AS(
    SELECT
        station_id
        ,variable_id
        ,sampling_operation
        ,day
        ,day_of_month
        ,CASE 
            WHEN month<=2 THEN 12+month
        END as month
        ,CASE 
            WHEN month<=2 THEN year-1
        END as year
        ,value       
    FROM daily_data
    WHERE month in (1,12)
    UNION ALL
    SELECT * FROM daily_data
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
    FROM extended_data ed
    JOIN wx_station st ON st.id = ed.station_id
    WHERE year BETWEEN {{start_year}} AND {{end_year}}
      AND month BETWEEN {{month}} AND {{month}}+2
    GROUP BY st.name, variable_id, year, sampling_operation
)
SELECT
    station
    ,variable_id
    ,{{month}} AS "month"
    ,ad.year
    ,value AS "3-Aggregation"
    ,ROUND(((100*"count")::numeric/atd.total_days::numeric),1) AS "Aggregation (% of days)"
FROM aggreated_data ad
LEFT JOIN aggreation_total_days atd ON atd.year=ad.year
ORDER BY year