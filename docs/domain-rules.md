# Domain Rules

This lab's working quantity rule:

```text
Available = On Hand - Allocated
```

Allocated is the quantity promised to orders. Those units are still on
hand until they ship. Available is what a new order may still take.

Allocated cannot exceed on hand. That keeps available at zero or above.
Allocating 60 of 100 pencils is legal: on hand 100, allocated 60,
available 40.

## Pencil walkthrough

Start with 100 pencils on hand and nothing promised.

```text
                On hand  Allocated  Available  Picked  Shipped
Start               100          0        100       0        0
Purchase of 40      140          0        140       0        0
Allocate 30         140         30        110       0        0
Pick those 30       140         30        110      30        0
Ship those 30       110          0        110       0       30
```

**Purchase.** On hand and available increase by 40. Nothing is
promised yet.

**Allocate.** Allocated becomes 30 and available drops to 110. On hand
stays 140. The pencils are still in the bin.

**Pick.** Picked becomes 30. On hand, allocated, and available stay
the same. The pencils left the bin, are still in the building, and are
still promised to Order A.

**Ship.** On hand and allocated both drop by 30. Available stays 110.
Picked returns to 0 because those units left the building. Shipped
becomes 30.

Packing sits between pick and ship. It does not change on hand,
allocated, or available. It records that the 30 picked pencils are
inside a package.

## Invariants

* Available = On Hand - Allocated.
* On hand, allocated, available, picked, and shipped are never
  negative.
* Allocated never exceeds on hand.
* Picked never exceeds allocated. A pick is still a promise.
* A pick does not change available.
* A shipment decreases on hand and allocated by the same quantity, so
  available does not change.
* Shipped units are no longer on hand and no longer allocated.
