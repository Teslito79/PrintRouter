CorelDRAW templates that PrintHub copies into every product item.

<width>x<height>.cdr   one template per size, in whole mm, e.g. 85x55.cdr for
                       business cards. Either way round works: an order of
                       55 x 85 mm also gets 85x55.cdr. For folded products use
                       the open (flat) size, e.g. 170x55.cdr for folded cards.

<product id>.cdr       optional: a template for one product, named after the
                       website's product id, e.g. bcard.cdr. It is used instead
                       of the size template for that product.

blank.cdr              the fallback, used when no template above matches.

Upper or lower case in the names doesn't matter.

PrintHub picks the template when the order arrives, in this order:
<product id>.cdr, <width>x<height>.cdr, <height>x<width>.cdr, blank.cdr.
The copy is named after the order: PH-10240.cdr (or PH-10240-01.cdr,
PH-10240-02.cdr when one order has several products). It is made once and never
replaced. Options.txt in the item folder and the PrintHub details say which
template was used, e.g. "CorelDRAW template: 85x55.cdr".

Printing the sheet to PDF:
1. Open PH-10240.cdr from PrintHub and place the customer's design.
2. In CorelDRAW choose File > Print, then Print preview. Set the rows and
   columns (how many pieces on the sheet) and press Apply.
3. Choose the printer "Microsoft Print to PDF" and print.
4. Save the file as PH-10240.pdf in the same item folder (keep that name).
5. Press Layout done in PrintHub. PrintRouter prints that PDF at actual size.
