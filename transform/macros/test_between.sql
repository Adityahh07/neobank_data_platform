{#- Generic test: fails for every row where the column is below min_value or,
    if max_value is given, above max_value. -#}
{% test between(model, column_name, min_value, max_value=none) %}
select *
from {{ model }}
where {{ column_name }} < {{ min_value }}
{%- if max_value is not none %} or {{ column_name }} > {{ max_value }}{% endif %}
{% endtest %}
