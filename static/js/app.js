// Global state
let products = [];
let cart = [];

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
});

// Setup event listeners
function setupEventListeners() {
    cartBtn.addEventListener('click', openCart);
    closeCart.addEventListener('click', closeCartSidebar);
    overlay.addEventListener('click', closeCartSidebar);

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
                                    <button class="size-option" data-size="${size}" data-price="${variantPrice}" onclick="selectSize(this, ${product.id})">
                                        ${size}
                                        <span class="variant-price">$${variantPrice.toFixed(0)}</span>
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

    console.log(`🔧 Quantity Update: ${currentQuantity} + ${change} = ${newQuantity}`);

    // Don't allow quantity to go below 1 with minus button
    if (newQuantity < 1) {
        console.log('❌ Blocked: quantity would go below 1');
        return;
    }

    try {
        // Delete all existing items for this product/size
        for (const index of itemGroup.indices.sort((a, b) => b - a)) {
            await fetch(`/api/cart/${index}`, { method: 'DELETE' });
        }

        // Add new item with updated quantity
        const response = await fetch('/api/cart', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                product_id: itemGroup.product_id,
                size: itemGroup.size,
                quantity: newQuantity,
                variant_price: itemGroup.variant_price
            })
        });

        if (response.ok) {
            console.log('✅ Quantity update successful, reloading cart...');
            await loadCart(); // Reload cart to get updated state
        } else {
            throw new Error('Failed to update quantity');
        }
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
        top: 20px;
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

    const total = cart.reduce((sum, item) => sum + (item.product.price * item.quantity), 0);
    const itemCount = cart.reduce((sum, item) => sum + item.quantity, 0);

    showNotification(`Checkout: ${itemCount} items for $${total.toFixed(2)} - Integration with payment processor needed!`);
});