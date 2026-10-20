select geolocation_zip_code_prefix, latitude, longitude
from {{ ref('geolocation_by_zip') }}
where (latitude is not null and (latitude < -33.8 or latitude > 5.3))
   or (longitude is not null and (longitude < -73.99 or longitude > -34.7))
