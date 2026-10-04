{#- Pseudonymise a customer ID: salted SHA-256, so the same customer always gets
    the same key but the original ID can't be read. The salt comes from the
    PII_SALT environment variable; the default is for local development only. -#}
{% macro mask_id(column) -%}
    sha256('{{ env_var("PII_SALT", "dev-only-salt") }}' || {{ column }})
{%- endmacro %}
