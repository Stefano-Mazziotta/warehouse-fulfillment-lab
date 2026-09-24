# Domain Glossary

Business language for this lab. Use it to explain a warehouse without
mentioning code.

These are public industry meanings, not ShipHero's private design.
Where this lab simplifies a rule, the entry says so.

## How an order moves

```text
Sales Channel
      ↓
    Order
      ↓
  Allocation
      ↓
   Picking
      ↓
   Packing
      ↓
  Shipment
      ↓
   Carrier
      ↓
  Tracking
```

The sales channel sells. The warehouse reserves stock, picks it, packs
it, and hands packages to a carrier. Tracking is how the channel and
the customer learn the package left.

## Commerce

**Sales channel.** Where the customer buys: a Shopify store, a
marketplace, a wholesale portal. The channel creates the commercial
order. The warehouse fulfills it.

**Store.** One selling presence on a channel. A brand can have several
stores. In a 3PL, each client can connect several stores.

**Customer.** The buyer. The warehouse ships to the customer. The
channel owns the customer relationship.

**Product.** The catalog item: a name and a description. A product is
not a quantity.

**Variant.** One version of a product, such as a size or a color. The
catalog talks about variants. The warehouse usually talks about SKUs.
Often one variant is one SKU.

**SKU.** Stock keeping unit. The id the warehouse uses to receive,
count, store, allocate, pick, and ship one specific item. Two colors
are two SKUs even when they are one product.

**Order.** A request to deliver quantities of SKUs to a destination.
It comes from a sales channel, or from an EDI purchase order or
warehouse shipping order. An order is not inventory, and it is not yet
a shipment.

**Order item.** One SKU and a quantity on an order. Partial
fulfillment is decided per item, not only for the whole order.

## Warehouse

**Warehouse.** A building where stock is stored and orders are
fulfilled. One company, or one 3PL, can run several warehouses.

**Location / bin.** A specific place inside a warehouse: an aisle, a
shelf, a bin. Stock is counted at a location, not only for the
building. A picker is sent to a bin.

**Inventory.** The quantity of a SKU the warehouse is responsible for.
It is several quantities, not one number.

**Stock movement.** A recorded change in where units are, or which
state they are in. Receiving, allocation, pick, pack, ship, return,
adjustment, and bin transfer are movements. If the books and the floor
disagree, the movements are how you explain the difference.

### Quantity states

**On hand.** Units physically in the building now. That includes units
already promised to orders, and units that cannot be sold.

**Allocated.** Units reserved for specific orders. They cannot be
promised to someone else.

**Available.** Units that can still be promised to a new order.

In this lab the working definition is:

```text
Available = On Hand - Allocated
```

Real warehouses often also subtract units that are picked but not
shipped, on hold, or in a non-sellable location. Say which formula you
mean when you explain it.

**Pickable.** On-hand units in locations a picker is allowed to pick
from. Stock in receiving, quarantine, or a damaged bin can be on hand
and still not pickable.

**Sellable.** Units that may be promised to customers.

**Non-sellable.** Units still in the building that must not be
allocated: damaged, expired, quarantine, or samples.

**Picked.** Units taken from the bin for an order. They are no longer
in the pick face, and they have not left the building.

**Packed.** Picked units placed into a package. They are still in the
warehouse.

**Shipped.** Units that have left on a carrier. On hand drops when the
goods leave, not when the order is created.

A purchase arrival increases on hand. Allocation moves units from
available to allocated. A pick moves them to picked. Shipping is the
movement that takes them out of the warehouse.

## Fulfillment

**Allocation.** Reserving available units for an order's items. After
it succeeds, those units are allocated and no longer available. If two
orders want the last unit, only one allocation can succeed.

**Picking.** The physical work of taking allocated items out of bins.

**Pick list.** The instruction for one piece of picking work: which
orders, SKUs, quantities, and bins. It is what a person can execute.

**Pick wave.** A group of orders released to the floor together, so
people walk the warehouse once for many orders. Some operations call
this a pick batch. A wave is how work is grouped. A pick list is the
work one person sees.

**Tote.** The container a picker carries from the bins to packing.
Often one tote is one order, or one slot in a batch, so items from
different orders stay separate.

**Packing.** Putting picked items into shippable packages and
confirming the quantities.

**Package.** One box or mailer. One order can become several packages.
A package has contents, quantities, weight, dimensions, and a
packaging type.

**Shipment.** The record that one or more packages were handed to a
carrier. One order can have more than one shipment when it ships in
parts.

**Shipping label.** The carrier document on the package. It says where
the package goes and how the movement is billed. It is created before
or as the package ships.

**Tracking number.** The carrier's id for a package or shipment. The
sales channel and the customer use it after the goods leave.

**Return.** Units coming back from a customer. They are not sellable
until someone receives them, inspects them, and puts them in a
pickable location or leaves them non-sellable.

## 3PL

A third-party logistics provider runs the warehouse for other
companies, called clients. A brand that stores only its own goods is
not acting as a 3PL for that stock.

**Who owns the inventory.** The client. The 3PL holds it and must not
lose it or promise it twice.

**Who owns the order.** The client owns the sale. The 3PL owns the
warehouse work to fulfill it.

**Who pays.** The client pays the 3PL. Public industry practice is to
bill receiving, storage, picks, packages, and shipments. The exact
fees are a contract, not a universal rule.

**Client isolation.** Each client's units are counted separately. An
order for client A can never be filled from client B's stock.

**Same SKU, two clients.** The code can look the same. The stock is
still different. Isolation is client plus SKU, not SKU alone.

**Multi-warehouse.** One client can keep stock in several buildings.
Allocation then chooses which warehouse can fulfill the order.

**Client-specific rules.** Packaging, carriers, services, and whether
a short order may ship in part can differ per client.

## Order lifecycle

This lab's teaching sequence:

```text
CREATED
   ↓
ALLOCATED
   ↓
PICKING
   ↓
PICKED
   ↓
PACKED
   ↓
SHIPPED
```

**Created.** The order exists. Nothing is reserved yet.

**Allocated.** Inventory is reserved for the order.

**Picking.** Someone is working the pick.

**Picked.** The pick is confirmed.

**Packed.** Packages are built from what was picked.

**Shipped.** Packages were handed to the carrier.

These are business operations, not a generic status change:
allocate, start picking, complete picking, pack, ship.

### Exceptions

**Cancellation.** Stop the work and release the allocation if the
order has not shipped. Units already picked have to go back to a
location.

**Backorder.** The order, or one item, cannot be allocated because
available stock is short. It waits until stock is received.

**Partial fulfillment.** Ship some items or quantities now and leave
the rest open.

**Partial pick.** The picker could not take the full allocated
quantity. That is a short pick. The order is not fully picked.

**Failed shipment.** The label or the carrier handoff did not finish.
The goods have not left. The order is not shipped.

## Packing and shipping

A packing configuration says which picked units go in which package.

A valid one satisfies all of these:

* Quantities of an item across packages add up to what this shipment
  is supposed to contain.
* Packed quantity never exceeds what was picked for that order item.
* Nothing is packed that was not on the order.
* Each unit is in only one package.
* Each package has a weight, dimensions, and a packaging type.
* Each package that ships has a carrier, a shipping service, a label,
  and a tracking number.

### Words that are not the same

**Carrier.** The company that moves the package, such as UPS or FedEx.

**Shipping service.** A product that carrier sells, such as ground or
overnight.

**Shipping method.** What the merchant offers the customer, such as
"Standard". It maps to a carrier service. The storefront can say
Standard while the warehouse buys UPS Ground.

**Rate.** The price a carrier quotes for a package on a service,
before anyone buys a label.

**Label.** Proof the carrier accepted the request to move the package.

**Shipment.** The warehouse record that the packages left.

Changing UPS for FedEx changes the carrier. It does not change the
meaning of "ship this order."

## EDI

EDI is electronic data interchange: standard business documents
between companies. The warehouse cares about what event the document
represents. The same document can arrive twice; the business outcome
must happen once.

**850 — Purchase order.** Buyer to supplier. "Buy these goods." It is
not, by itself, a pick instruction.

**940 — Warehouse shipping order.** Client to the 3PL. "Ship these
items." This is the order the warehouse executes.

**945 — Warehouse shipping advice.** Warehouse to the client. "This is
what we actually shipped." It can differ from the 940 when there was
a short.

**856 — Advance ship notice.** Shipper to the receiver of the goods.
"These cartons are coming, and here is what is in them," so the
destination can plan receiving. The 945 tells the client the warehouse
finished. The 856 tells the consignee what is arriving.

**846 — Inventory inquiry / advice.** A stock snapshot, or a request
for one, between partners.

**810 — Invoice.** A bill for goods or for services.

## Easy to mix up

**On hand vs available.** On hand is in the building. Available can
still be promised. Allocated units are on hand and are not available.

**Allocated vs picked.** Allocated is a promise. Picked means someone
took the units out of the bin.

**Pick list vs pick wave.** The list is one person's work. The wave is
the group of orders released together.

**Package vs shipment.** The package is the box. The shipment is the
handoff of one or more packages to a carrier.

**Carrier vs shipping service.** The carrier is the company. The
service is which of that company's products you bought.

**940 vs 945 vs 856.** The 940 says what to ship. The 945 says what
the warehouse shipped. The 856 tells the receiver what is on the way.
