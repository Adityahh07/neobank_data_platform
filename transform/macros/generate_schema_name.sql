{#- Use the configured schema name as-is (silver, gold, pii) instead of dbt's
    default "<target_schema>_<custom_schema>" (e.g. main_silver). -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name | trim if custom_schema_name else target.schema }}
{%- endmacro %}
