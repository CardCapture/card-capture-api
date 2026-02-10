-- Format all school names from ALL CAPS to proper case
UPDATE high_schools_directory 
SET name = INITCAP(name) 
WHERE name = UPPER(name) AND name != INITCAP(name);