# The 40-Point Release Check

**Quailworks Engineering · quailworks.co/engineering**

The checklist we run on every drawing before it reaches a supplier. Each point is a question with a yes/no
answer. A drawing goes out only when all 40 are yes, or the no is written down and agreed.

Free to use and share. If your team runs it on its next release, count the noes: that's your release backlog.

---

## A. Title block and release (6)

1. **Part number, title and revision** match the model, the BOM and the PLM record.
2. **Units, projection symbol (first or third angle) and general scale** are stated.
3. **The general tolerance standard** is named (for example ISO 2768-mK, or your own table) and fits the process.
4. **The drawing standard** is named (ISO GPS / BS 8888 or ASME Y14.5) and the drawing follows it throughout.
5. **The revision block** describes what changed, in words a supplier understands, with date and approver.
6. **Drawn, checked and approved** fields are filled by three roles, not one person three times.

## B. Views and dimensions (8)

7. **Every feature is fully defined** once: nothing missing, nothing dimensioned twice.
8. **No dimension is measured off a hidden line**, a silhouette or a tangent edge that won't exist on the part.
9. **Dimensions come from datums**, not chained from feature to feature where the stack-up matters.
10. **Reference dimensions are marked as reference** and never carry a tolerance.
11. **Section and detail views** are where the supplier needs them, labelled and at a readable scale.
12. **Hole tables or patterns** state count, size, depth and position in one place.
13. **Basic (theoretically exact) dimensions** are boxed wherever a position or profile tolerance uses them.
14. **The drawing matches the released model**: same revision, no unexplained differences.

## C. Datums and GD&T (8)

15. **Datums are real, accessible features** that the part is located on in assembly and in inspection.
16. **The datum reference frame** constrains every degree of freedom the function needs, in a sensible order.
17. **Position, profile and orientation tolerances** are used where function depends on them, not ± on everything.
18. **Material condition modifiers (MMC/LMC)** are used where they buy clearance and cost, and only there.
19. **Every feature control frame is readable**: right symbol, zone shape, value and datum order.
20. **Tolerance stack-ups at critical interfaces** have been checked against the mating parts.
21. **Flatness, parallelism and perpendicularity on sealing and bearing faces** are specified where needed.
22. **Inspection is possible**: every GD&T callout can be measured on a CMM or with a gauge.

## D. Tolerances and fits (5)

23. **No tolerance is tighter than function needs**; each tight one has a reason.
24. **Fits for bearings, pins and bushes** use the standard fit designation (for example H7/g6) with limits shown.
25. **Threads** carry size, pitch, class, depth and any locking or insert callout.
26. **Surface texture (Ra)** is set only on functional faces, with a general value for the rest.
27. **Edge breaks and fillets** are specified (for example "break all sharp edges 0.2-0.5 x 45°").

## E. Material, treatment and finish (5)

28. **Material** is named by standard and grade (for example EN AW-7075-T651, 17-4PH H1025), not a trade name.
29. **Heat treatment** gives the condition and how it is verified (hardness and location).
30. **Coatings and finishes** name the process and specification, thickness, masking and what happens to threads.
31. **For composites**: ply table, orientations, material, cure cycle and inspection are on the drawing or referenced.
32. **Special processes** (welding, bonding, NDT) name the procedure and the acceptance standard.

## F. Manufacturability (5)

33. **Every feature can be machined or formed** with standard tools: radii, depths and access checked.
34. **Wall thicknesses, rib ratios and draft** suit the process (casting, moulding, additive, sheet metal).
35. **Stock size and process route** are sensible for the quantity: prototype and production may differ.
36. **The supplier has been asked** about any feature that drives cost, before release, not after.
37. **Weight and centre of gravity** are within target and recorded.

## G. Assembly and inspection (3)

38. **The part has been checked in the assembly model**: clearances, tool access and fastener grip lengths.
39. **Critical-to-function characteristics** are flagged for first-article inspection.
40. **Notes are numbered, short and unambiguous**, and none contradicts the views.

---

*Want a second pair of eyes? Send us one released drawing under NDA and we'll mark it up against these 40
points within 48 hours, free. hello@quailworks.co*

*Quailworks sp. z o.o. · ul. Mikołaja Reja 34, 26-225 Gowarczów, Poland · KRS 0001108506*
