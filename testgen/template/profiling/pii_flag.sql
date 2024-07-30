-- Primary Screen:  Alpha
WITH screen
   AS ( SELECT id  AS profile_results_id,
               table_name, column_name,
               CASE
                  WHEN functional_data_type IN ('Person Full Name', 'Person Given Name', 'Person Last Name') THEN 'B/NAME/Individual'
                  
                  WHEN LOWER(column_name) SIMILAR TO '%(maiden|surname)%'                      THEN 'B/NAME/Individual'
                  
                  WHEN functional_data_type = 'Historical Date'
                     AND LOWER(column_name) SIMILAR TO '%(dob|birth)%'                         THEN 'B/DEMO/Birthdate'
                  
                  WHEN LOWER(column_name)
                     SIMILAR TO '%(nationality|race|ethnicity|gender|sex|marital)%'            THEN 'B/DEMO/Demographic'
                  
                  WHEN LOWER(column_name) ILIKE '%med%record%'                                 THEN 'A/DEMO/Medical'
                  
                  WHEN LOWER(column_name) SIMILAR TO '%(password|pwd|auth)%'                   THEN 'A/ID/Security'
                  
                  WHEN max_length < 10
                   AND avg_embedded_spaces < 0.1
                   AND (column_name ILIKE 'pin%' OR column_name ILIKE '%pin')                  THEN 'A/ID/Security'
                  
                  WHEN std_pattern_match = 'SSN'
                     AND LOWER(column_name) SIMILAR TO '%(ss|soc|sec)%'                        THEN 'A/ID/SSN'
                  
                  WHEN TRIM(fn_parsefreq(top_patterns, 1, 2))
                          IN ('NNNNNNNNN', 'NNN-NN-NNNN', 'NNN NN NNNN')
                     AND LEFT(min_text, 1) = '9'
                     AND avg_length BETWEEN 8.8 AND 11.2
                     AND LOWER(column_name) SIMILAR TO '%(tax|tin|fed)%'                       THEN 'A/ID/Tax'
                  
                  WHEN TRIM(fn_parsefreq(top_patterns, 1, 2))
                          IN ('NNNNNNNNN', 'ANNNNNNNN')
                     AND avg_length BETWEEN 8.8 AND 9.2
                     AND LOWER(column_name) SIMILAR TO '%(passp|pp)%'                          THEN 'A/ID/Passport'
                  
                  WHEN std_pattern_match = 'CREDIT_CARD'
                     AND LOWER(column_name) SIMILAR TO '%(credit|card|cc|acct|account)%'       THEN 'A/ID/Credit'
                  
                  WHEN TRIM(fn_parsefreq(top_patterns, 1, 2))
                          ILIKE '[Aa]{6}[A-Za-z0-9]{2}N{0,3}'
                     AND TRIM(fn_parsefreq(top_patterns, 2, 2))
                          ILIKE '[Aa]{6}[A-Za-z0-9]{2}N{0,3}'
                     AND avg_length BETWEEN 7.8 AND 11.2
                     AND LOWER(column_name) SIMILAR TO '%(swift|bic)%'                         THEN 'A/ID/Bank'
                  
                  WHEN max_length <= 34
                     AND UPPER(LEFT(TRIM(fn_parsefreq(top_patterns, 1, 2)), 2))
                          = 'AA'
                     AND (column_name ILIKE 'iban%' OR column_name ILIKE '%iban')              THEN 'A/ID/Bank'
                  
                  WHEN avg_length BETWEEN 5 AND 20
                     AND LOWER(column_name) SIMILAR TO '%(bank|checking|saving|debit)%'        THEN 'A/ID/Bank'
                  
                  WHEN avg_embedded_spaces < 0.5
                     AND avg_length < 20
                     AND (LOWER(column_name) SIMILAR TO '%(dr|op)%lic%'
                        OR LOWER(column_name) SIMILAR TO '%(driver|license|operator)%')        THEN 'A/ID/License'
                  
                  WHEN LOWER(column_name) IN ('patient_id', 'pat_id')                          THEN 'A/ID/Medical'

                  WHEN LOWER(column_name) IN ('member_id')                                     THEN 'B/ID/Commercial'

               END AS pii_flag
          
          FROM profile_results p
         WHERE profile_run_id = '{PROFILE_RUN_ID}'
           AND general_type = 'A' )
UPDATE profile_results
   SET pii_flag = screen.pii_flag
  FROM screen
 WHERE screen.pii_flag > ''
   AND profile_results.id = screen.profile_results_id;

-- Secondary Screen - Alpha
  WITH table_pii_counts
          AS ( SELECT table_name, COUNT(pii_flag) AS pii_ct
                 FROM profile_results
                WHERE profile_run_id = '{PROFILE_RUN_ID}'
                GROUP BY table_name ),
       screen
          AS ( SELECT id  AS profile_results_id,
                      p.table_name, p.column_name,
                      CASE
                         WHEN functional_data_type = 'Email'                                           THEN 'B/CONTACT/Email'
                         WHEN functional_data_type IN ('Address', 'City', 'State', 'Zip')
                                                                                                       THEN 'B/CONTACT/Address'
                         WHEN functional_data_type = 'Phone'
                                                                                                       THEN 'B/CONTACT/Phone'
                         
                         WHEN LOWER(column_name) SIMILAR TO '%(insur|health|med|patient)%'
                                                                                                       THEN 'A/DEMO/Medical'
                         
                         WHEN LOWER(column_name) SIMILAR TO '%(vehicle|vin|auto|car)%'
                            AND avg_length BETWEEN 16 AND 18
                            AND max_length < 20
                            AND TRIM(fn_parsefreq(top_patterns, 1, 2))
                                   = 'AAANAAAAANNNNNNNN'                                               THEN 'B/ID/Auto'
                         
                         WHEN LOWER(column_name) SIMILAR TO
                              '%(voice|fingerprint|retina|auth|biometric|iris|face_recog)%'
                                                                                                       THEN 'A/ID/Security'
                         
                         WHEN LOWER(column_name) = 'dna'
                            OR LOWER(column_name) ILIKE '%\_dna'
                            OR LOWER(column_name) ILIKE 'dna\_%'
                                                                                                       THEN 'A/DEMO/Demographic'
                         
                         WHEN column_name ILIKE '%rout%'
                            AND avg_length BETWEEN 8.8 AND 11.2
                            AND TRIM(fn_parsefreq(top_patterns, 1, 2))
                                   IN ('NNNNNNNNN', 'NNNN-NNNN-N')                                     THEN 'C/ID/Bank'
                         
                         WHEN LOWER(column_name) SIMILAR TO '%(salary|income|wage)%'
                                                                                                       THEN 'B/DEMO/Financial'
                         
                         WHEN LOWER(column_name) SIMILAR TO '%(user_id|userid)%'
                                                                                                       THEN 'C/ID/Security'
                      
                      END AS pii_flag
                 FROM profile_results p
                      INNER JOIN table_pii_counts t
                                 ON (p.table_name = t.table_name)
                WHERE p.profile_run_id = '{PROFILE_RUN_ID}'
                  AND p.general_type = 'A'
                  AND p.pii_flag IS NULL
                  AND t.pii_ct > 1 )
UPDATE profile_results
   SET pii_flag = screen.pii_flag
  FROM screen
 WHERE screen.pii_flag > ''
   AND profile_results.id = screen.profile_results_id;
