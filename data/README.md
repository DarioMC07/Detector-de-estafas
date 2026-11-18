# Datos exclusivamente demostrativos

`mensajes_demo.csv` contiene 80 mensajes ficticios escritos para mostrar el flujo del proyecto, 40 por clase. No son denuncias verificadas ni una muestra representativa del tráfico real. Los dominios de ejemplo no deben visitarse.

Las métricas obtenidas con este archivo **no validan la eficacia real**. El vocabulario y los patrones de estos ejemplos son artificiales y sencillos. La detección puede fallar incluso en casos que una persona considere evidentes.

Formato UTF-8: columnas `texto` y `etiqueta`; etiquetas exactas `legitimo` y `fraudulento`. Para otros datos ficticios utiliza `--demo` al entrenar. No incluyas datos personales ni credenciales reales. Consulta el README principal para incorporar datos reales y evitar filtraciones entre particiones.
