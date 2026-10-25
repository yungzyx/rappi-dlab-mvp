-- clean_html() con las entidades que quedaban en el catálogo real tras la primera limpieza (30-09-2026):
-- &ccedil; («A&ccedil;aí» → «Açaí») y &ordm;. Misma lógica que 014; CREATE OR REPLACE porque 014 ya está aplicada.
CREATE OR REPLACE FUNCTION clean_html(t text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE STRICT
AS $$
DECLARE
    named CONSTANT text[][] := ARRAY[
        ['nbsp', ' '], ['aacute', 'á'], ['eacute', 'é'], ['iacute', 'í'], ['oacute', 'ó'], ['uacute', 'ú'],
        ['Aacute', 'Á'], ['Eacute', 'É'], ['Iacute', 'Í'], ['Oacute', 'Ó'], ['Uacute', 'Ú'],
        ['ntilde', 'ñ'], ['Ntilde', 'Ñ'], ['uuml', 'ü'], ['Uuml', 'Ü'], ['ccedil', 'ç'], ['Ccedil', 'Ç'],
        ['iexcl', '¡'], ['iquest', '¿'], ['ordm', 'º'], ['ordf', 'ª'],
        ['ndash', '–'], ['mdash', '—'], ['hellip', '…'], ['bull', '•'], ['middot', '·'], ['rarr', '→'],
        ['laquo', '«'], ['raquo', '»'], ['ldquo', '“'], ['rdquo', '”'], ['lsquo', '‘'], ['rsquo', '’'],
        ['quot', '"'], ['apos', ''''], ['acute', '´'], ['deg', '°'], ['reg', '®'], ['copy', '©'],
        ['trade', '™'], ['gt', '>'], ['lt', '<']
    ];
    m text[];
    i int;
BEGIN
    -- Sin etiquetas ni entidades, el texto sale intacto: si no, cambiaría el hash de miles de documentos sin HTML
    -- (espacios dobles, saltos de línea) y se volverían a embeber sin motivo.
    IF t !~ '<[a-zA-Z/!][^>]*>|&(#[0-9]{1,6}|[a-zA-Z]{2,8});' THEN
        RETURN t;
    END IF;
    t := regexp_replace(t, '<[^>]*>', ' ', 'g');  -- etiquetas: fuera, dejando un espacio entre palabras
    FOR i IN 1 .. array_length(named, 1) LOOP
        t := replace(t, '&' || named[i][1] || ';', named[i][2]);
    END LOOP;
    FOR m IN SELECT regexp_matches(t, '&#([0-9]{1,6});', 'g') LOOP  -- numéricas: &#8211; → –
        IF m[1]::int BETWEEN 32 AND 1114111 THEN
            t := replace(t, '&#' || m[1] || ';', chr(m[1]::int));
        END IF;
    END LOOP;
    t := replace(t, '&amp;', '&');  -- al final, para no decodificar dos veces (&amp;lt; queda «&lt;»)
    t := regexp_replace(t, '\s+', ' ', 'g');
    RETURN btrim(regexp_replace(t, ' ([,.;:!?)])', '\1', 'g'));  -- «profundo</b>, sin» → «profundo, sin»
END
$$;
