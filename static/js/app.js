// Global state
let products = [];
let cart = [];
let stripeInstance = null;
let stripePublishableKey = null;
let lastRecipientDetails = null;
let lastCalculatedOrder = null;
let checkoutButtonEl = null;
let checkoutButtonOriginalLabel = 'Proceed to Checkout';
let printfulCountries = [];
let countriesLoaded = false;

// DOM elements
const productsGrid = document.getElementById('productsGrid');
const cartBtn = document.getElementById('cartBtn');
const cartSidebar = document.getElementById('cartSidebar');
const closeCart = document.getElementById('closeCart');
const cartCount = document.getElementById('cartCount');
const cartItems = document.getElementById('cartItems');
const cartTotal = document.getElementById('cartTotal');
const overlay = document.createElement('div');
overlay.className = 'overlay';
document.body.appendChild(overlay);

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    loadProducts();
    loadCart();
    setupEventListeners();
    initializeStripe();
    loadCountries();
});

// Setup event listeners
function setupEventListeners() {
    cartBtn.addEventListener('click', openCart);
    closeCart.addEventListener('click', closeCartSidebar);
    overlay.addEventListener('click', closeCartSidebar);
}

async function initializeStripe() {
    try {
        const response = await fetch('/api/stripe-config');
        if (!response.ok) {
            throw new Error('Failed to load Stripe configuration');
        }
        const data = await response.json();
        if (data.publishableKey) {
            stripePublishableKey = data.publishableKey;
            stripeInstance = Stripe(stripePublishableKey);
        }
    } catch (error) {
        console.warn('Stripe configuration unavailable:', error);
    }
}

async function loadCountries() {
    const fallbackCountries = [
        { code: 'US', name: 'United States' },
        { code: 'CA', name: 'Canada' },
        { code: 'GB', name: 'United Kingdom' },
        { code: 'AU', name: 'Australia' },
        { code: 'DE', name: 'Germany' }
    ];

    try {
        const response = await fetch('/api/countries');
        if (!response.ok) {
            throw new Error('Failed to load countries');
        }
        const data = await response.json();
        printfulCountries = Array.isArray(data.countries) && data.countries.length > 0
            ? data.countries
            : fallbackCountries;
    } catch (error) {
        console.warn('Falling back to default country list:', error);
        printfulCountries = fallbackCountries;
    } finally {
        countriesLoaded = true;
    }
}

function getCountryOptionsMarkup(selectedCode = 'US') {
    const countries = printfulCountries.length > 0
        ? printfulCountries
        : [{ code: 'US', name: 'United States' }];

    return countries
        .sort((a, b) => a.name.localeCompare(b.name))
        .map(country => {
            const isSelected = country.code === selectedCode;
            return `<option value="${country.code}" ${isSelected ? 'selected' : ''}>${country.name}</option>`;
        })
        .join('');
}
// Load products from API
async function loadProducts() {
    try {
        showLoading();
        const response = await fetch('/api/products');
        products = await response.json();
        renderProducts(products);
    } catch (error) {
        console.error('Error loading products:', error);
        showError('Failed to load products');
    }
}

// Load cart from API
async function loadCart() {
    try {
        const response = await fetch('/api/cart');
        cart = await response.json();
        updateCartUI();
    } catch (error) {
        console.error('Error loading cart:', error);
    }
}

// Render products
function renderProducts(productsToRender) {
    if (!productsToRender || productsToRender.length === 0) {
        productsGrid.innerHTML = '<div class="loading">No products found</div>';
        return;
    }

    productsGrid.innerHTML = productsToRender.map(product => `
        <div class="product-card" data-product-id="${product.id}">
            <div class="product-image">
                <img src="${product.image_url}" alt="${product.name}" onerror="this.style.display='none'; this.parentElement.innerHTML='Product Image';">
            </div>
            <div class="product-info">
                <h3 class="product-name">${product.name}</h3>
                <p class="product-description">${product.description}</p>
                <div class="product-price">
                    ${product.price_range ? product.price_range : `$${product.price.toFixed(2)}`}
                </div>
                ${product.sizes && product.sizes.length > 1 ? `
                    <div class="size-selector">
                        <label>Size:</label>
                        <div class="size-options">
                            ${product.sizes.map((size, index) => {
                                const variant = product.variants?.find(v => v.name === size);
                                let variantPrice = variant ? (variant.retail_price || variant.price / 100) : product.price;
                                variantPrice = parseFloat(variantPrice) || product.price;
                                return `
                                    <button class="size-option" data-size="${size}" data-price="${variantPrice.toFixed(2)}" onclick="selectSize(this, ${product.id})">
                                        ${size}
                                        <span class="variant-price">$${variantPrice.toFixed(2)}</span>
                                    </button>
                                `;
                            }).join('')}
                        </div>
                    </div>
                ` : ''}
                <button class="add-to-cart-btn" onclick="addToCart(${product.id})" ${!product.in_stock ? 'disabled' : ''}>
                    ${product.in_stock ? 'Add to Cart' : 'Out of Stock'}
                </button>
            </div>
        </div>
    `).join('');
}

// Select size
function selectSize(element, productId) {
    const productCard = document.querySelector(`[data-product-id="${productId}"]`);
    const sizeOptions = productCard.querySelectorAll('.size-option');
    sizeOptions.forEach(option => option.classList.remove('selected'));
    element.classList.add('selected');
}

// Add to cart
async function addToCart(productId) {
    const product = products.find(p => p.id === productId);
    if (!product || !product.in_stock) return;

    let selectedSize = 'One Size';
    let variantPrice = product.price;

    if (product.sizes && product.sizes.length > 1) {
        const productCard = document.querySelector(`[data-product-id="${productId}"]`);
        const selectedSizeElement = productCard.querySelector('.size-option.selected');
        if (!selectedSizeElement) {
            alert('Please select a size');
            return;
        }
        selectedSize = selectedSizeElement.dataset.size;
        variantPrice = selectedSizeElement ? parseFloat(selectedSizeElement.dataset.price) : product.price;
    }

    try {
        const response = await fetch('/api/cart', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                product_id: productId,
                size: selectedSize,
                quantity: 1,
                variant_price: variantPrice
            })
        });

        if (response.ok) {
            await loadCart(); // Reload cart from server
            showNotification('Item added to cart!');

            // Reset size selection
            const productCard = document.querySelector(`[data-product-id="${productId}"]`);
            const sizeOptions = productCard.querySelectorAll('.size-option');
            sizeOptions.forEach(option => option.classList.remove('selected'));
        } else {
            throw new Error('Failed to add to cart');
        }
    } catch (error) {
        console.error('Error adding to cart:', error);
        showNotification('Failed to add item to cart', 'error');
    }
}

// Update cart UI
function updateCartUI() {
    // Group cart items by product_id and size to combine quantities
    const groupedCart = {};
    let totalItems = 0;

    cart.forEach((item, index) => {
        const key = `${item.product_id}-${item.size}`;
        if (!groupedCart[key]) {
            groupedCart[key] = {
                product: item.product,
                product_id: item.product_id,
                size: item.size,
                quantity: 0,
                variant_price: item.variant_price,
                indices: []
            };
        }
        groupedCart[key].quantity += item.quantity;
        groupedCart[key].indices.push(index);
        totalItems += item.quantity;
    });

    cartCount.textContent = totalItems;

    if (Object.keys(groupedCart).length === 0) {
        cartItems.innerHTML = '<div class="empty-cart">Your cart is empty</div>';
        cartTotal.textContent = '0.00';
        return;
    }

    // Sort keys alphabetically for consistent ordering
    const sortedKeys = Object.keys(groupedCart).sort();

    cartItems.innerHTML = sortedKeys.map((key, displayIndex) => {
        const item = groupedCart[key];
        const itemPrice = item.variant_price || item.product.price;
        return `
        <div class="cart-item">
            <div class="cart-item-image">
                <img src="${item.product.image_url}" alt="${item.product.name}" onerror="this.style.display='none'; this.parentElement.innerHTML='📦';">
            </div>
            <div class="cart-item-details">
                <div class="cart-item-name">${item.product.name}</div>
                <div class="cart-item-size">Size: ${item.size}</div>
                <div class="cart-item-price">$${(itemPrice * item.quantity).toFixed(2)}</div>
                <div class="cart-item-quantity">
                    <button class="quantity-btn" onclick="updateQuantity(${displayIndex}, -1)">-</button>
                    <span class="quantity-display">${item.quantity}</span>
                    <button class="quantity-btn" onclick="updateQuantity(${displayIndex}, 1)">+</button>
                </div>
                <button class="remove-item" onclick="removeFromCart(${displayIndex})">Remove</button>
            </div>
        </div>
    `;
    }).join('');

    const total = sortedKeys.reduce((sum, key) => {
        const item = groupedCart[key];
        const itemPrice = item.variant_price || item.product.price;
        return sum + (itemPrice * item.quantity);
    }, 0);
    cartTotal.textContent = total.toFixed(2);
}

// Update quantity
async function updateQuantity(displayIndex, change) {
    // Rebuild grouped cart to find the correct item
    const groupedCart = {};
    cart.forEach((item, index) => {
        const key = `${item.product_id}-${item.size}`;
        if (!groupedCart[key]) {
            groupedCart[key] = {
                product: item.product,
                product_id: item.product_id,
                size: item.size,
                variant_price: item.variant_price,
                indices: []
            };
        }
        groupedCart[key].indices.push(index);
    });

    // Sort keys alphabetically for consistent ordering
    const sortedKeys = Object.keys(groupedCart).sort();
    const actualKey = sortedKeys[displayIndex];
    const itemGroup = groupedCart[actualKey];

    if (!actualKey || !itemGroup || !Array.isArray(itemGroup.indices)) {
        console.error('Invalid cart state in quantity update, reloading...');
        await loadCart();
        return;
    }

    const currentQuantity = itemGroup.indices.length;
    const newQuantity = currentQuantity + change;

    // Don't allow quantity to go below 1 with minus button
    if (newQuantity < 1) {
        // Keep at least 1 item, don't allow going to 0
        return;
    }

    try {
        if (change > 0) {
            // Simple: add one more item
            const response = await fetch('/api/cart', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    product_id: itemGroup.product_id,
                    size: itemGroup.size,
                    quantity: 1,  // Add just one item
                    variant_price: itemGroup.variant_price
                })
            });

            if (!response.ok) {
                throw new Error('Failed to add item');
            }
        } else if (change < 0 && currentQuantity > 1) {
            // Simple: remove just one item (the last one in the group)
            const indexToRemove = itemGroup.indices[itemGroup.indices.length - 1];
            const response = await fetch(`/api/cart/${indexToRemove}`, { method: 'DELETE' });

            if (!response.ok) {
                throw new Error('Failed to remove item');
            }
        }

        await loadCart(); // Reload cart to get updated state
    } catch (error) {
        console.error('Error updating quantity:', error);
        showNotification('Failed to update quantity', 'error');
        await loadCart(); // Reload cart to reset state on error
    }
}

// Remove from cart
async function removeFromCart(displayIndex) {
    try {
        // Rebuild grouped cart to find the actual items to remove
        const groupedCart = {};
        cart.forEach((item, index) => {
            const key = `${item.product_id}-${item.size}`;
            if (!groupedCart[key]) {
                groupedCart[key] = {
                    indices: []
                };
            }
            groupedCart[key].indices.push(index);
        });

        // Sort keys alphabetically for consistent ordering
        const sortedKeys = Object.keys(groupedCart).sort();
        const actualKey = sortedKeys[displayIndex];

        if (!actualKey || !groupedCart[actualKey] || !Array.isArray(groupedCart[actualKey].indices)) {
            console.error('Invalid cart state, reloading...');
            await loadCart();
            return;
        }

        const indicesToRemove = groupedCart[actualKey].indices.sort((a, b) => b - a); // Remove from back to front

        // Remove all cart items for this product/size combination
        for (const index of indicesToRemove) {
            const response = await fetch(`/api/cart/${index}`, { method: 'DELETE' });
            if (!response.ok) {
                throw new Error('Failed to remove item');
            }
        }

        await loadCart(); // Reload cart from server
    } catch (error) {
        console.error('Error removing from cart:', error);
        showNotification('Failed to remove item', 'error');
        await loadCart(); // Reload to reset state on error
    }
}


// Cart controls
function openCart() {
    cartSidebar.classList.add('open');
    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeCartSidebar() {
    cartSidebar.classList.remove('open');
    overlay.classList.remove('active');
    document.body.style.overflow = '';
}

// Utility functions
function showLoading() {
    productsGrid.innerHTML = '<div class="loading">Loading products...</div>';
}

function showError(message) {
    productsGrid.innerHTML = `<div class="loading" style="color: #e74c3c;">${message}</div>`;
}

function showNotification(message, type = 'success') {
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        background: ${type === 'success' ? '#27ae60' : '#e74c3c'};
        color: white;
        padding: 16px 24px;
        border-radius: 8px;
        z-index: 10000;
        font-weight: 500;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        animation: slideIn 0.3s ease;
    `;
    notification.textContent = message;
    document.body.appendChild(notification);

    // Add animation
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
    `;
    document.head.appendChild(style);

    setTimeout(() => {
        notification.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => {
            document.body.removeChild(notification);
            document.head.removeChild(style);
        }, 300);
    }, 3000);
}

// Handle navigation
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();

        // Scroll to products section
        document.querySelector('.products').scrollIntoView({
            behavior: 'smooth'
        });
    });
});

// Handle checkout
document.querySelector('.checkout-btn').addEventListener('click', () => {
    if (cart.length === 0) {
        showNotification('Your cart is empty', 'error');
        return;
    }

    // Show shipping calculator modal
    showShippingCalculator();
});

// Show shipping calculator modal
async function showShippingCalculator() {
    if (!countriesLoaded) {
        await loadCountries();
    }

    const existingModal = document.querySelector('[data-checkout-modal="true"]');
    if (existingModal) {
        existingModal.remove();
    }

    checkoutButtonEl = null;
    lastRecipientDetails = null;
    lastCalculatedOrder = null;

    const modal = document.createElement('div');
    modal.dataset.checkoutModal = 'true';
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.5);
        z-index: 10000;
        display: flex;
        align-items: center;
        justify-content: center;
    `;

    const selectedCountry = lastRecipientDetails?.country || 'US';
    const countryOptions = getCountryOptionsMarkup(selectedCountry);

    modal.innerHTML = `
        <div style="background: white; padding: 24px; border-radius: 8px; max-width: 500px; width: 90%; max-height: 95vh; overflow-y: auto;">
            <h3 style="margin-bottom: 24px; color: #0a0a0a;">Calculate Total Cost</h3>
            <form id="shippingForm">
                <div style="margin-bottom: 16px;">
                    <label style="display: block; margin-bottom: 8px; font-weight: 600; color: #0a0a0a;">Full Name</label>
                    <input type="text" name="name" required style="width: 100%; padding: 12px; border: 1px solid #f0f0f0; border-radius: 4px;">
                </div>
                <div style="margin-bottom: 16px;">
                    <label style="display: block; margin-bottom: 8px; font-weight: 600; color: #0a0a0a;">Email</label>
                    <input type="email" name="email" required style="width: 100%; padding: 12px; border: 1px solid #f0f0f0; border-radius: 4px;">
                </div>
                <div style="margin-bottom: 16px;">
                    <label style="display: block; margin-bottom: 8px; font-weight: 600; color: #0a0a0a;">Address</label>
                    <input type="text" name="address1" required style="width: 100%; padding: 12px; border: 1px solid #f0f0f0; border-radius: 4px;">
                </div>
                <div style="margin-bottom: 16px;">
                    <label style="display: block; margin-bottom: 8px; font-weight: 600; color: #0a0a0a;">City</label>
                    <input type="text" name="city" required style="width: 100%; padding: 12px; border: 1px solid #f0f0f0; border-radius: 4px;">
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 16px;">
                    <div>
                        <label style="display: block; margin-bottom: 8px; font-weight: 600; color: #0a0a0a;">State/Province</label>
                        <input type="text" name="state" required style="width: 100%; padding: 12px; border: 1px solid #f0f0f0; border-radius: 4px;">
                    </div>
                    <div>
                        <label style="display: block; margin-bottom: 8px; font-weight: 600; color: #0a0a0a;">ZIP/Postal Code</label>
                        <input type="text" name="zip" required style="width: 100%; padding: 12px; border: 1px solid #f0f0f0; border-radius: 4px;">
                    </div>
                    <div>
                        <label style="display: block; margin-bottom: 8px; font-weight: 600; color: #0a0a0a;">Country</label>
                        <select name="country" required style="width: 100%; padding: 12px; border: 1px solid #f0f0f0; border-radius: 4px;">
                            ${countryOptions}
                        </select>
                    </div>
                </div>
                <div style="display: flex; gap: 12px; justify-content: flex-end;">
                    <button type="button" onclick="closeCheckoutModal(this)" style="padding: 12px 24px; border: 1px solid #f0f0f0; background: white; cursor: pointer; border-radius: 4px;">Cancel</button>
                    <button type="submit" style="padding: 12px 24px; background: #00FFCC; color: #0a0a0a; border: none; cursor: pointer; border-radius: 4px; font-weight: 600;">Calculate Total</button>
                </div>
            </form>
            <div id="costBreakdown" style="margin-top: 24px; display: none;">
                <h4 style="margin-bottom: 16px; color: #0a0a0a;">Cost Breakdown</h4>
                <div id="breakdownContent"></div>
            </div>
        </div>
    `;

    document.body.appendChild(modal);
    modal.addEventListener('click', (event) => {
        if (event.target === modal) {
            closeCheckoutModal();
        }
    });

    const form = modal.querySelector('#shippingForm');
    if (lastRecipientDetails) {
        Object.entries(lastRecipientDetails).forEach(([key, value]) => {
            if (!value) return;
            const field = form.elements.namedItem(key);
            if (field) {
                field.value = value;
            }
        });
    }

    // Handle form submission
    document.getElementById('shippingForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(e.target);
        const recipient = Object.fromEntries(formData.entries());

        try {
            const response = await fetch('/api/calculate-total-cost', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ recipient })
            });

            if (response.ok) {
                const costData = await response.json();
                lastRecipientDetails = recipient;
                displayCostBreakdown(costData);
            } else {
                throw new Error('Failed to calculate costs');
            }
        } catch (error) {
            console.error('Error calculating costs:', error);
            showNotification('Failed to calculate shipping costs', 'error');
        }
    });

    function displayCostBreakdown(costData) {
        const breakdownDiv = document.getElementById('costBreakdown');
        const contentDiv = document.getElementById('breakdownContent');

        const shippingNote = costData.breakdown.shipping_note ? ' (Estimated)' : '';
        const taxNote = costData.breakdown.tax_note ? ' (Estimated)' : '';

        contentDiv.style.color = '#0a0a0a';

        contentDiv.innerHTML = `
            <div style="display: grid; gap: 8px; margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between;">
                    <span>Subtotal:</span>
                    <span>$${costData.breakdown.subtotal.toFixed(2)}</span>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span>Shipping${shippingNote}:</span>
                    <span>$${costData.breakdown.shipping.toFixed(2)}</span>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span>Taxes${taxNote}:</span>
                    <span>$${costData.breakdown.taxes.toFixed(2)}</span>
                </div>
                <div style="border-top: 1px solid #f0f0f0; padding-top: 8px; margin-top: 8px; display: flex; justify-content: space-between; font-weight: 700; font-size: 18px;">
                    <span>Total:</span>
                    <span style="color: #0a0a0a;">$${costData.total.toFixed(2)}</span>
                </div>
            </div>
            <button type="button" data-role="proceed-checkout" style="width: 100%; padding: 16px; background: #0a0a0a; color: white; border: none; cursor: pointer; border-radius: 4px; font-weight: 600;">
                Proceed to Checkout
            </button>
        `;

        breakdownDiv.style.display = 'block';
        lastCalculatedOrder = costData;
        checkoutButtonEl = contentDiv.querySelector('button[data-role="proceed-checkout"]');
        if (checkoutButtonEl) {
            checkoutButtonOriginalLabel = checkoutButtonEl.textContent || 'Proceed to Checkout';
            checkoutButtonEl.disabled = false;
            checkoutButtonEl.addEventListener('click', proceedToCheckout);
        }
    }
}

function setCheckoutButtonState(disabled, label) {
    if (!checkoutButtonEl) {
        return;
    }
    checkoutButtonEl.disabled = disabled;
    if (label) {
        checkoutButtonEl.textContent = label;
    }
}

async function proceedToCheckout() {
    if (!stripePublishableKey) {
        showNotification('Checkout is currently unavailable. Please try again later.', 'error');
        return;
    }

    if (!lastRecipientDetails || !lastCalculatedOrder) {
        showNotification('Please calculate your total before proceeding to checkout.', 'error');
        return;
    }

    if (!stripeInstance) {
        stripeInstance = Stripe(stripePublishableKey);
    }

    setCheckoutButtonState(true, 'Redirecting...');

    try {
        const response = await fetch('/api/create-checkout-session', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ recipient: lastRecipientDetails })
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const message = errorData.detail || 'Failed to start checkout. Please try again.';
            throw new Error(message);
        }

        const data = await response.json();

        if (data.publishableKey && data.publishableKey !== stripePublishableKey) {
            stripePublishableKey = data.publishableKey;
            stripeInstance = Stripe(stripePublishableKey);
        }

        const redirectResult = await stripeInstance.redirectToCheckout({
            sessionId: data.checkout_session_id
        });

        if (redirectResult?.error) {
            throw new Error(redirectResult.error.message);
        }
    } catch (error) {
        console.error('Error starting checkout:', error);
        showNotification(error.message || 'Failed to start checkout. Please try again.', 'error');
        setCheckoutButtonState(false, checkoutButtonOriginalLabel);
    }
}

function closeCheckoutModal(trigger) {
    const modal = trigger
        ? trigger.closest('[data-checkout-modal="true"]')
        : document.querySelector('[data-checkout-modal="true"]');
    if (modal) {
        modal.remove();
    }
    checkoutButtonEl = null;
    lastCalculatedOrder = null;
    lastRecipientDetails = null;
}
