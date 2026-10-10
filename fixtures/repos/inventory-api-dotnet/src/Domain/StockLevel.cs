namespace Acme.Inventory.Domain;

public static class StockMath
{
    public static int Clamp(int quantity) => quantity < 0 ? 0 : quantity;
}

// Calls made from inside properties: a block getter and an expression-bodied
// property, beside a method as the control.
public class StockLevel
{
    public int Raw { get; init; }

    public int OnHand
    {
        get { return StockMath.Clamp(Raw); }
    }

    public int Display => StockMath.Clamp(Raw);

    public int Normalised()
    {
        return StockMath.Clamp(Raw);
    }
}
