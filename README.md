# SundAI Merch Shop

A simple merchandise shop for SundAI, built with FastAPI backend and vanilla JavaScript/CSS frontend.

## Features

- **Product Catalog**: Browse SundAI merchandise with categories
- **Shopping Cart**: Add/remove items, adjust quantities
- **Stripe Checkout**: Secure payments with automatic post-payment fulfillment
- **Printful Fulfillment**: Orders are created and confirmed with Printful after successful payment
- **Responsive Design**: Works on desktop and mobile
- **Clean UI**: Minimalist design inspired by sundai.club
- **REST API**: Full backend API for products and cart management

## Tech Stack

- **Backend**: FastAPI (Python)
- **Frontend**: Vanilla HTML, CSS, JavaScript
- **Styling**: Custom CSS with Inter font
- **Images**: PIL-generated placeholders

## Environment Variables

Create a `.env` file (or otherwise export the variables) with the following keys:

- `PRINTFUL_API_KEY` - Printful API token used to load products and create orders
- `PRINTFUL_STORE_ID` - Optional but recommended; restricts product queries to your store
- `STRIPE_SECRET_KEY` - Stripe secret key used on the server to create checkout sessions
- `STRIPE_PUBLISHABLE_KEY` - Stripe publishable key used by the client to redirect to Checkout
- `SESSION_SECRET` - Secret used by FastAPI session middleware (defaults to a development value)
- `ESTIMATED_TAX_RATE` - Optional override for the fallback tax rate (defaults to 0.085)

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the application:
```bash
python main.py
```

3. Open your browser and go to `http://localhost:8000`

## API Endpoints

- `GET /` - Storefront UI
- `GET /api/products` - Fetch merchandise catalog
- `GET /api/products/{product_id}` - Fetch a single product
- `GET /api/cart` - Retrieve the current session cart
- `POST /api/cart` - Add an item to the cart (session-scoped)
- `DELETE /api/cart/{item_id}` - Remove an item from the cart
- `POST /api/calculate-total-cost` - Estimate subtotal, shipping, and taxes for the active cart
- `GET /api/stripe-config` - Publishable Stripe key for the client
- `POST /api/create-checkout-session` - Create a Stripe Checkout session for the current cart
- `POST /api/checkout-success` - Finalize successful Stripe payments and trigger Printful fulfillment
- `GET /api/countries` - List Printful-supported destination countries for the checkout form
- Printful helper endpoints: `/api/sync-products`, `/api/store-info`, `/api/catalog-products`, `/api/store-products`, `/api/create-order`, `/api/confirm-order/{order_id}`, `/api/order-status/{order_id}`

## Project Structure

```
shop/
├── main.py                 # FastAPI application
├── requirements.txt        # Python dependencies
├── static/
│   ├── index.html         # Frontend HTML
│   ├── css/
│   │   └── style.css      # Styles
│   ├── js/
│   │   └── app.js         # Frontend JavaScript
│   └── images/
│       ├── tshirt.jpg     # Product images
│       ├── hoodie.jpg
│       ├── cap.jpg
│       └── tote.jpg
└── README.md              # This file
```

## Customization

- **Products**: Modify the `products` list in `main.py` to add/change products
- **Styling**: Edit `static/css/style.css` to customize the appearance
- **Images**: Replace placeholder images in `static/images/`

## Future Enhancements

- Payment processing integration
- User accounts and authentication
- Order history
- Inventory management
- Admin interface for product management
