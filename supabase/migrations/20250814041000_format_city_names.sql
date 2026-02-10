-- Format all city names from ALL CAPS to proper case
UPDATE high_schools_directory 
SET city = INITCAP(city) 
WHERE city = UPPER(city) AND city != INITCAP(city) AND city IS NOT NULL;