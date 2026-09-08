---
name: prepare-a-replacement-shipment-draft-from-a-support-ticket
description: "Use this workflow to Prepare a replacement shipment draft from a support ticket. Review unresolved questions and bind inputs from the current workspace."
---

# Prepare a replacement shipment draft from a support ticket

Prepare a replacement shipment draft from a support ticket.

## Inputs

- `{{customer_shipping_address}}`: private_token; required; customer_shipping_address.
- `{{order_id}}`: string; required; order_id.

## Before starting

- Open the source task in the current workspace and inspect its current state.

## Procedure

1. **Reach Replacement shipment form**

   Before: Current recorded context: Replacement requested for order {{order_id}}. Customer shipping address is protected.
   Do: Open the workflow for Replacement shipment form in shipping and confirm that its current form or page is ready.
   Locate: Replacement shipment form; Application: shipping
   Verify: Confirm the current run reaches this state: Replacement shipment form is open.
   Evidence: observed; e3, e1, e4.

2. **Populate Order reference**

   Before: Current recorded context: Replacement shipment form is open.
   Do: Locate the editable field for Order reference in shipping and enter {{order_id}}. Use the current run's input and compare the populated field with that input before continuing.
   Locate: Order reference; Application: shipping; Identify the field by its label and purpose in the current layout.
   Verify: Confirm the current run reaches this state: Order reference {{order_id}} is present. Verify that Order reference matches the current input {{order_id}}.
   Evidence: observed; e5, e4, e6.

3. **Set the requested choice for Replacement item**

   Before: Inspect the current form and the source task.
   Before: Recorded source guidance: Select the replacement item shown on the support ticket before preparing the draft.
   Do: Locate Replacement item in shipping, select Replacement item, and confirm that the selection is retained.
   Locate: Replacement item; Application: shipping; Identify the field by its label and purpose in the current layout.
   Verify: Confirm the current run reaches this state: Replacement item is selected.
   Evidence: observed; e10, e8, e11, e9.

4. **Populate Customer shipping address**

   Before: Current recorded context: Replacement item is selected.
   Do: Locate the editable field for Customer shipping address in shipping and enter {{customer_shipping_address}}. Use the current run's input and compare the populated field with that input before continuing.
   Locate: Customer shipping address; Application: shipping; Identify the field by its label and purpose in the current layout.
   Verify: Confirm the current run reaches this state: Shipping address field contains the protected customer shipping address. Verify that Customer shipping address matches the current input {{customer_shipping_address}}.
   Evidence: observed; e12, e11, e13.

5. **Complete the recorded transition for Prepare draft**

   Before: Current recorded context: Shipping address field contains the protected customer shipping address.
   Do: Locate the control whose function is Prepare draft in shipping. Activate it once, then inspect the resulting state before taking another action.
   Locate: Prepare draft; Application: shipping; Identify the control by its function and resulting state; its label may differ.
   Verify: Confirm the current run reaches this state: Replacement shipment draft ready for review. Order, replacement item, and destination are populated.
   Evidence: observed; e16, e13, e17.
   Recovery (user_confirmed): If the current form shows the recorded error: Validation message: select the replacement item. — Select the replacement item shown on the support ticket before preparing the draft. Recheck the corrected state before continuing.


## Outcome checks

- Verify in the new run: Destination value equals the selected source value. (recording: passed; source: core_verifier; c1)
- Verify in the new run: Draft contains the selected order, replacement item, and matching shipping destination; no purchase was made. (recording: passed; source: core_verifier; c2)

## Execution boundary

Bind private inputs to fresh opaque references supplied by PLVA. The current runtime owns permissions, approvals, and execution. This package grants none. Inspect semantic targets in the current visual state; historical coordinates are not replay instructions.

The recording is evidence of one demonstration. Review acceptance is not a successful rerun. Consult `validation.json` for the specific checks performed and pending live execution.

Detailed step references are in `evidence-map.json`; the local source recording may be unavailable in another workspace.
