# Ada Retail Skill

## Cuándo usar este skill
Cuando `industry_type = "retail"` o la empresa es distribuidora, comercializadora,
tienda, almacén, supermercado, o cualquier negocio que venda productos físicos.
Se carga como complemento de otros skills (excel-analysis, document-search).

## Conocimiento de dominio retail

### Métricas que Ada DEBE calcular para retail
1. **Margen bruto %**: (Venta - Costo) / Venta × 100
2. **Margen neto %**: (Venta - Costo - Gastos) / Venta × 100 (si hay gastos)
3. **Rotación de inventario**: Costo de ventas / Inventario promedio (días)
4. **Clasificación ABC**: A=80% ventas, B=15%, C=5%
5. **Cartera vencida**: Total facturas vencidas / Total facturado × 100
6. **Días mora promedio**: Promedio de días de atraso en pagos
7. **Top 10 clientes por venta**: Ranking + % de participación
8. **Top 10 productos por margen**: Ranking de rentabilidad
9. **Productos margen negativo**: Lista completa (riesgo)
10. **Ranking vendedores**: Por venta total y por margen
11. **Concentración de clientes**: % que representan los top 5

### Columnas que Ada busca automáticamente
Ada detecta columnas por nombre fuzzy (sin importar mayúsculas o tildes):
- **Venta**: venta, ventas, total_venta, valor_venta, monto, total, ingreso
- **Costo**: costo, costos, costo_total, valor_costo, costo_venta
- **Cliente**: cliente, nombre_cliente, razon_social, comprador
- **Vendedor**: vendedor, asesor, ejecutivo, representante
- **Producto**: producto, item, referencia, sku, descripcion, articulo
- **Fecha**: fecha, fecha_venta, date, periodo
- **Cantidad**: cantidad, qty, unidades, und

### Umbrales de alerta retail
| Indicador | ⚠️ Warning | 🔴 Crítico |
|---|---|---|
| Margen bruto | < 15% | < 5% |
| Cartera vencida | > 10% de ventas | > 20% de ventas |
| Concentración top 5 | > 50% de ventas | > 70% de ventas |
| Stock sin movimiento | > 60 días | > 90 días |
| Productos margen negativo | > 3 productos | > 10 productos |

## Lenguaje y contexto retail colombiano

### Términos que Ada usa naturalmente
- "Cartera" = cuentas por cobrar (no portafolio de inversión)
- "Rotación" = velocidad de venta del inventario
- "ABC" = clasificación Pareto de productos/clientes
- "Mora" = atraso en pagos
- "Margen" = diferencia entre venta y costo
- "Ticket promedio" = venta promedio por transacción

### Moneda y formato
- Moneda: COP (pesos colombianos)
- Formato: punto para miles, coma para decimales
- Ejemplo: $12.500.000,00
- Si el valor es > 1 millón, abreviar: $12,5M

## Recomendaciones estándar por situación

### Si hay productos con margen negativo:
💡 "Revisar pricing de [productos]. Están generando pérdida en cada venta. Evaluar: subir precio, negociar con proveedor, o descontinuar."

### Si hay alta concentración de clientes:
⚠️ "El [X]% de las ventas depende de [N] clientes. Riesgo alto si alguno se va. Diversificar cartera de clientes."

### Si la cartera vencida es alta:
🔴 "Cartera vencida al [X]% de ventas. Flujo de caja en riesgo. Priorizar cobro de facturas con mora > 60 días."

### Si un vendedor domina las ventas:
💡 "El [X]% de ventas las genera [vendedor]. Evaluar si es oportunidad (replicar su método) o riesgo (dependencia)."
